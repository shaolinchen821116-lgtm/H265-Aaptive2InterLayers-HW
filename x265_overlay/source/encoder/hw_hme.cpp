/****************************************************************************
 * Hardware-oriented three-stage motion search.
 *
 * PME: original luma, 1/4 resolution, exhaustive asymmetric window. Mode 0
 *      preserves (SAD >> shift) * MVD_bits(0,0); mode 1 uses
 *      SAD + adaptive(QP, texture) * MVD_bits with selectable attractor.
 * IME: reconstructed luma, full-pel exhaustive window around scaled PME,
 *      SAD + sqrt(lambda) * MVD_bits with selected AMVP attractor.
 * FME: reconstructed luma, AMVP guard, 8 half-pel then 8 quarter-pel neighbors,
 *      SAD + sqrt(lambda) * MVD_bits with selected AMVP attractor.
 ****************************************************************************/

#include "common.h"
#include "cudata.h"
#include "frame.h"
#include "lowres.h"
#include "search.h"
#include "hw_hme.h"

#include <stdio.h>
#include <stdlib.h>

using namespace X265_NS;

namespace {

struct HardwareHMEAggregate
{
    Lock lock;
    uint64_t blocks[3];
    uint64_t pmeCandidates;
    uint64_t imeCandidates;
    uint64_t fmeCandidates;
    uint64_t pmeZero;
    uint64_t imeChangedPme;
    uint64_t fmeChangedIme;
    uint64_t textureClass[3];
    uint64_t pmeUsedAmvp;
    bool registered;

    HardwareHMEAggregate()
    {
        memset(blocks, 0, sizeof(blocks));
        pmeCandidates = imeCandidates = fmeCandidates = 0;
        pmeZero = imeChangedPme = fmeChangedIme = 0;
        memset(textureClass, 0, sizeof(textureClass));
        pmeUsedAmvp = 0;
        registered = false;
    }
};

HardwareHMEAggregate g_hwHmeStats;

static void printHardwareHMEStats()
{
    ScopedLock lock(g_hwHmeStats.lock);
    uint64_t total = g_hwHmeStats.blocks[0] + g_hwHmeStats.blocks[1] + g_hwHmeStats.blocks[2];
    if (!total)
        return;

    fprintf(stderr,
        "x265 [info]: HW-HME summary: PU8=%llu PU16=%llu PU32=%llu; "
        "avg candidates PME=%.2f IME=%.2f FME=%.2f; PME-zero=%.2f%% "
        "IME-changed=%.2f%% FME-changed=%.2f%%; texture=%llu/%llu/%llu AMVP-attractor=%.2f%%\n",
        (unsigned long long)g_hwHmeStats.blocks[0],
        (unsigned long long)g_hwHmeStats.blocks[1],
        (unsigned long long)g_hwHmeStats.blocks[2],
        (double)g_hwHmeStats.pmeCandidates / total,
        (double)g_hwHmeStats.imeCandidates / total,
        (double)g_hwHmeStats.fmeCandidates / total,
        100.0 * (double)g_hwHmeStats.pmeZero / total,
        100.0 * (double)g_hwHmeStats.imeChangedPme / total,
        100.0 * (double)g_hwHmeStats.fmeChangedIme / total,
        (unsigned long long)g_hwHmeStats.textureClass[0],
        (unsigned long long)g_hwHmeStats.textureClass[1],
        (unsigned long long)g_hwHmeStats.textureClass[2],
        100.0 * (double)g_hwHmeStats.pmeUsedAmvp / total);
}

static void recordHardwareHMEStats(int size, const HardwareHMETrace& trace)
{
    ScopedLock lock(g_hwHmeStats.lock);
    if (!g_hwHmeStats.registered)
    {
        atexit(printHardwareHMEStats);
        g_hwHmeStats.registered = true;
    }

    int idx = size == 8 ? 0 : (size == 16 ? 1 : 2);
    g_hwHmeStats.blocks[idx]++;
    g_hwHmeStats.pmeCandidates += trace.pmeCandidates;
    g_hwHmeStats.imeCandidates += trace.imeCandidates;
    g_hwHmeStats.fmeCandidates += trace.fmeCandidates;
    g_hwHmeStats.pmeZero += !trace.pmeMvDs.notZero();
    g_hwHmeStats.imeChangedPme += trace.imeMvFullPel != trace.imeCenterFullPel;
    g_hwHmeStats.fmeChangedIme += trace.fmeMvQPel != hwImeFullPelToQPel(trace.imeMvFullPel);
    g_hwHmeStats.textureClass[X265_MIN((int)trace.pmeTextureClass, 2)]++;
    g_hwHmeStats.pmeUsedAmvp += trace.pmeUsedAmvp;
}

static inline uint32_t sadBlock(const pixel* a, intptr_t aStride,
                                const pixel* b, intptr_t bStride,
                                int width, int height)
{
    uint32_t sad = 0;
    for (int y = 0; y < height; y++)
    {
        for (int x = 0; x < width; x++)
            sad += abs((int)a[x] - (int)b[x]);
        a += aStride;
        b += bStride;
    }
    return sad;
}

static inline int manhattan(const MV& mv)
{
    return abs(mv.x) + abs(mv.y);
}

static inline uint32_t meanGradient8bit(const pixel* src, intptr_t stride,
                                        int width, int height)
{
    uint32_t sum = 0;
    uint32_t edges = 0;
    for (int y = 0; y < height; y++)
    {
        for (int x = 1; x < width; x++)
            sum += abs((int)src[x] - (int)src[x - 1]);
        if (y)
            for (int x = 0; x < width; x++)
                sum += abs((int)src[x] - (int)src[x - stride]);
        edges += (uint32_t)(width - 1) + (y ? (uint32_t)width : 0);
        src += stride;
    }
    uint32_t activity = edges ? (sum + (edges >> 1)) / edges : 0;
#if X265_DEPTH > 8
    activity = (activity + (1 << (X265_DEPTH - 9))) >> (X265_DEPTH - 8);
#endif
    return activity;
}

static inline bool betterPme(uint64_t cost, uint32_t sad, uint32_t bits, const MV& mv,
                             uint64_t bestCost, uint32_t bestSad, uint32_t bestBits, const MV& bestMv)
{
    if (cost != bestCost) return cost < bestCost;
    if (sad != bestSad) return sad < bestSad;
    if (bits != bestBits) return bits < bestBits;
    if (manhattan(mv) != manhattan(bestMv)) return manhattan(mv) < manhattan(bestMv);
    if (mv.y != bestMv.y) return mv.y < bestMv.y;
    return mv.x < bestMv.x;
}

static inline bool betterRd(uint32_t cost, uint32_t sad, const MV& mv,
                            uint32_t bestCost, uint32_t bestSad, const MV& bestMv)
{
    if (cost != bestCost) return cost < bestCost;
    if (sad != bestSad) return sad < bestSad;
    if (manhattan(mv) != manhattan(bestMv)) return manhattan(mv) < manhattan(bestMv);
    if (mv.y != bestMv.y) return mv.y < bestMv.y;
    return mv.x < bestMv.x;
}

}

int Search::hardwareMotionEstimate(Mode& interMode, const PredictionUnit& pu,
                                   int list, int refIdx, const MV& amvp,
                                   MV& outQPel, HardwareHMETrace* outTrace)
{
    HardwareHMETrace trace;
    CUData& cu = interMode.cu;
    X265_CHECK(pu.width == pu.height, "HW-HME requires a square PU\n");
    X265_CHECK(pu.width == 8 || pu.width == 16 || pu.width == 32,
               "HW-HME supports only PU 8/16/32\n");

    Frame* refFrame = m_slice->m_refFrameList[list][refIdx];
    ReferencePlanes* reconRef = &m_slice->m_mref[list][refIdx];
    m_me.setReferencePU(reconRef);
    const int absPartIdx = pu.cuAbsPartIdx + pu.puAbsPartIdx;
    const int fullX = (int)cu.m_cuPelX + (int)g_zscanToPelX[pu.puAbsPartIdx];
    const int fullY = (int)cu.m_cuPelY + (int)g_zscanToPelY[pu.puAbsPartIdx];

    /* Stage 1: PME on stored original-luma 1/4 planes. */
    const intptr_t curDsStride = m_frame->m_lowres.lumaStride / 2;
    const intptr_t refDsStride = refFrame->m_lowres.lumaStride / 2;
    const pixel* curDs = m_frame->m_lowres.lowerResPlane[0]
                       + (fullY >> 2) * curDsStride + (fullX >> 2);
    const pixel* refDsOrigin = refFrame->m_lowres.lowerResPlane[0]
                             + (fullY >> 2) * refDsStride + (fullX >> 2);
    const int dsWidth = pu.width >> 2;
    const int dsHeight = pu.height >> 2;
    const uint32_t activity = meanGradient8bit(curDs, curDsStride, dsWidth, dsHeight);
    const uint8_t textureClass = activity < (uint32_t)m_param->hwHmePmeTextureLow ? 0 :
                                 (activity < (uint32_t)m_param->hwHmePmeTextureHigh ? 1 : 2);
    static const uint16_t textureWeightQ8[3] = { 256, 160, 96 };
    const int sliceQp = x265_clip3(0, QP_MAX_MAX, m_slice->m_sliceQp);
    const uint32_t lambdaQ8 = (uint32_t)(x265_lambda_tab[sliceQp] * 256.0 + 0.5);
    const uint64_t combinedWeight = (uint64_t)lambdaQ8 *
                                    (uint32_t)m_param->hwHmePmeRateScaleQ8 *
                                    textureWeightQ8[textureClass];
    const uint32_t rateWeightQ8 = (uint32_t)((combinedWeight + (1 << 15)) >> 16);
    trace.pmeActivity = (uint16_t)X265_MIN(activity, 65535u);
    trace.pmeTextureClass = textureClass;
    trace.pmeRateWeightQ8 = (uint16_t)X265_MIN(rateWeightQ8, 65535u);

    MV safeMin, safeMax;
    const int pmeFullRange = X265_MAX(m_param->hwHmePmeRangeX,
                                     m_param->hwHmePmeRangeY) << 2;
    setSearchRange(cu, MV(0, 0), pmeFullRange, safeMin, safeMax);

    uint64_t bestPmeCost = ~(uint64_t)0;
    uint32_t bestPmeSad = MAX_UINT;
    uint32_t bestPmeBits = MAX_UINT;
    MV bestPmeDs(0, 0);
    const MV zero(0, 0);
    bool bestPmeUsedAmvp = false;

    for (int dy = -m_param->hwHmePmeRangeY; dy <= m_param->hwHmePmeRangeY; dy++)
    {
        const int fullDy = dy * 4;
        if (fullDy < safeMin.y || fullDy > safeMax.y)
            continue;
        for (int dx = -m_param->hwHmePmeRangeX; dx <= m_param->hwHmePmeRangeX; dx++)
        {
            const int fullDx = dx * 4;
            if (fullDx < safeMin.x || fullDx > safeMax.x)
                continue;

            MV dsMv(dx, dy);
            uint32_t sad = sadBlock(curDs, curDsStride,
                                    refDsOrigin + dy * refDsStride + dx, refDsStride,
                                    dsWidth, dsHeight);
            const MV qmv = hwPmeDsToQPel(dsMv);
            uint32_t bitsZero = m_me.bitcost(qmv, zero);
            uint32_t bitsAmvp = m_me.bitcost(qmv, amvp);
            uint32_t bits = bitsZero;
            bool usedAmvp = false;
            if (m_param->hwHmePmeAttractor == 1)
            {
                bits = bitsAmvp;
                usedAmvp = true;
            }
            else if (m_param->hwHmePmeAttractor == 2 && bitsAmvp + 1 < bitsZero)
            {
                bits = bitsAmvp + 1;
                usedAmvp = true;
            }
            uint64_t cost;
            if (m_param->hwHmePmeCostMode == 0)
                cost = ((uint64_t)(sad >> m_param->hwHmePmeSadShift)) * bitsZero;
            else
            {
                uint64_t rateCost = ((uint64_t)bits * combinedWeight + (1 << 23)) >> 24;
                cost = (uint64_t)sad + rateCost;
            }
            trace.pmeCandidates++;
            if (betterPme(cost, sad, bits, dsMv,
                          bestPmeCost, bestPmeSad, bestPmeBits, bestPmeDs))
            {
                bestPmeCost = cost;
                bestPmeSad = sad;
                bestPmeBits = bits;
                bestPmeDs = dsMv;
                bestPmeUsedAmvp = usedAmvp;
            }
        }
    }

    trace.pmeMvDs = bestPmeDs;
    trace.pmeSad = bestPmeSad;
    trace.pmeMvdBits = bestPmeBits;
    trace.pmeCost = bestPmeCost;
    trace.pmeUsedAmvp = bestPmeUsedAmvp;
    trace.imeCenterFullPel = hwPmeDsToImeFullPel(bestPmeDs);

    /* Stage 2: exhaustive full-pel IME on reconstructed reference luma. */
    m_me.setMVP(amvp);
    MV imeMin, imeMax;
    const int imeRange = X265_MAX(m_param->hwHmeImeRangeX, m_param->hwHmeImeRangeY);
    setSearchRange(cu, hwImeFullPelToQPel(trace.imeCenterFullPel), imeRange, imeMin, imeMax);
    imeMin.x = X265_MAX(imeMin.x, trace.imeCenterFullPel.x - m_param->hwHmeImeRangeX);
    imeMax.x = X265_MIN(imeMax.x, trace.imeCenterFullPel.x + m_param->hwHmeImeRangeX);
    imeMin.y = X265_MAX(imeMin.y, trace.imeCenterFullPel.y - m_param->hwHmeImeRangeY);
    imeMax.y = X265_MIN(imeMax.y, trace.imeCenterFullPel.y + m_param->hwHmeImeRangeY);

    const pixel* refOrigin = reconRef->getLumaAddr(pu.ctuAddr, absPartIdx);
    const intptr_t refStride = reconRef->lumaStride;
    uint32_t bestImeCost = MAX_UINT;
    uint32_t bestImeSad = MAX_UINT;
    uint32_t bestImeMvCost = 0;
    MV bestIme = trace.imeCenterFullPel;

    for (int y = imeMin.y; y <= imeMax.y; y++)
    {
        for (int x = imeMin.x; x <= imeMax.x; x++)
        {
            MV fullMv(x, y);
            MV qmv = hwImeFullPelToQPel(fullMv);
            uint32_t sad = m_me.bufSAD(refOrigin + y * refStride + x, refStride);
            uint32_t mvCost = m_me.mvcost(qmv);
            uint32_t cost = sad + mvCost;
            trace.imeCandidates++;
            if (betterRd(cost, sad, fullMv, bestImeCost, bestImeSad, bestIme))
            {
                bestImeCost = cost;
                bestImeSad = sad;
                bestImeMvCost = mvCost;
                bestIme = fullMv;
            }
        }
    }

    trace.imeMvFullPel = bestIme;
    trace.imeSad = bestImeSad;
    trace.imeMvCost = bestImeMvCost;

    /* Stage 3: IME seed plus one AMVP guard candidate, followed by one
     * half-pel ring and one quarter-pel ring around the better seed. The
     * guard costs one interpolation/SAD but prevents a failed coarse path
     * from discarding an already available temporal/spatial predictor. */
    static const int8_t ring[8][2] = {
        { 0, -1 }, { 1, -1 }, { 1, 0 }, { 1, 1 },
        { 0,  1 }, {-1,  1 }, {-1, 0 }, {-1,-1 }
    };

    MV bestQPel = hwImeFullPelToQPel(bestIme);
    uint32_t bestFmeSad = m_me.subpelSAD(reconRef, bestQPel);
    uint32_t bestFmeMvCost = m_me.mvcost(bestQPel);
    uint32_t bestFmeCost = bestFmeSad + bestFmeMvCost;
    trace.fmeCandidates = 1;

    MV guardedAmvp = amvp;
    cu.clipMv(guardedAmvp);
    if (guardedAmvp != bestQPel)
    {
        uint32_t sad = m_me.subpelSAD(reconRef, guardedAmvp);
        uint32_t mvCost = m_me.mvcost(guardedAmvp);
        uint32_t cost = sad + mvCost;
        trace.fmeCandidates++;
        if (betterRd(cost, sad, guardedAmvp, bestFmeCost, bestFmeSad, bestQPel))
        {
            bestFmeCost = cost;
            bestFmeSad = sad;
            bestFmeMvCost = mvCost;
            bestQPel = guardedAmvp;
        }
    }

    const MV halfCenter = bestQPel;
    for (int i = 0; i < 8; i++)
    {
        MV cand(halfCenter.x + ring[i][0] * 2, halfCenter.y + ring[i][1] * 2);
        MV clipped = cand;
        cu.clipMv(clipped);
        if (clipped != cand)
            continue;
        uint32_t sad = m_me.subpelSAD(reconRef, cand);
        uint32_t mvCost = m_me.mvcost(cand);
        uint32_t cost = sad + mvCost;
        trace.fmeCandidates++;
        if (betterRd(cost, sad, cand, bestFmeCost, bestFmeSad, bestQPel))
        {
            bestFmeCost = cost;
            bestFmeSad = sad;
            bestFmeMvCost = mvCost;
            bestQPel = cand;
        }
    }

    const MV quarterCenter = bestQPel;
    for (int i = 0; i < 8; i++)
    {
        MV cand(quarterCenter.x + ring[i][0], quarterCenter.y + ring[i][1]);
        MV clipped = cand;
        cu.clipMv(clipped);
        if (clipped != cand)
            continue;
        uint32_t sad = m_me.subpelSAD(reconRef, cand);
        uint32_t mvCost = m_me.mvcost(cand);
        uint32_t cost = sad + mvCost;
        trace.fmeCandidates++;
        if (betterRd(cost, sad, cand, bestFmeCost, bestFmeSad, bestQPel))
        {
            bestFmeCost = cost;
            bestFmeSad = sad;
            bestFmeMvCost = mvCost;
            bestQPel = cand;
        }
    }

    trace.fmeMvQPel = bestQPel;
    trace.fmeSad = bestFmeSad;
    trace.fmeMvCost = bestFmeMvCost;
    outQPel = bestQPel;

    if (m_param->bEnableHwHMEStats)
        recordHardwareHMEStats(pu.width, trace);
    if (outTrace)
        *outTrace = trace;

    return (int)bestFmeCost;
}
