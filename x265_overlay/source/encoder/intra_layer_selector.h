/****************************************************************************
 * Experimental I-slice layer selector: ALL, HIGH(32/16), LOW(16/8), AUTO.
 * The adaptive decision reads original 32x32 luma samples and QP only.
 ****************************************************************************/

#ifndef X265_INTRA_LAYER_SELECTOR_H
#define X265_INTRA_LAYER_SELECTOR_H

#include "common.h"
#include <stdlib.h>
#include <string.h>

namespace X265_NS {

enum IntraLayerExperimentMode
{
    INTRA_LAYER_MODE_ALL = 0,
    INTRA_LAYER_MODE_HIGH,
    INTRA_LAYER_MODE_LOW,
    INTRA_LAYER_MODE_ADAPTIVE,
    INTRA_LAYER_MODE_ONLY32,
    INTRA_LAYER_MODE_GATE32,
    INTRA_LAYER_MODE_CASCADE32
};

enum IntraLayerSet
{
    INTRA_LAYER_HIGH_32_16 = 0,
    INTRA_LAYER_LOW_16_8   = 1,
    INTRA_LAYER_ONLY_32    = 2,
    INTRA_LAYER_FULL_32_16_8 = 3
};

struct IntraLayerFeatures
{
    uint32_t sad32;
    uint32_t sad16;
    uint32_t sad8;
    uint32_t gradH;
    uint32_t gradV;
    uint32_t laplacian;
    uint32_t edge4;
    uint32_t edge8;
    uint32_t edge16;
    uint32_t edge32;
    uint32_t qstepQ8;
};

struct IntraLayerDecision
{
    IntraLayerSet layerSet;
    IntraLayerFeatures features;
    uint64_t highCostQ8;
    uint64_t lowCostQ8;
    uint32_t only32Probability;
};

#include "intra_only32_gate.h"

static inline IntraLayerExperimentMode getIntraLayerExperimentMode()
{
    const char* value = getenv("X265_INTRA_LAYER_MODE");
    if (!value || !strcmp(value, "all"))
        return INTRA_LAYER_MODE_ALL;
    if (!strcmp(value, "high"))
        return INTRA_LAYER_MODE_HIGH;
    if (!strcmp(value, "low"))
        return INTRA_LAYER_MODE_LOW;
    if (!strcmp(value, "adaptive") || !strcmp(value, "auto"))
        return INTRA_LAYER_MODE_ADAPTIVE;
    if (!strcmp(value, "only32"))
        return INTRA_LAYER_MODE_ONLY32;
    if (!strcmp(value, "gate32"))
        return INTRA_LAYER_MODE_GATE32;
    if (!strcmp(value, "cascade32"))
        return INTRA_LAYER_MODE_CASCADE32;
    return INTRA_LAYER_MODE_ALL;
}

static inline bool intraLayerStatsEnabled()
{
    const char* value = getenv("X265_INTRA_LAYER_STATS");
    return value && value[0] && strcmp(value, "0");
}

class IntraLayerSelector
{
public:
    IntraLayerDecision select(const pixel* src, intptr_t stride, int qp, int bitDepth) const
    {
        IntraLayerDecision out;
        IntraLayerFeatures& f = out.features;
        uint32_t sad16[4];
        uint32_t sad8By16[4];

        f.sad32 = normalizeSad(blockSadToMean(src, stride, 5), bitDepth);
        f.sad16 = 0;
        f.sad8 = 0;

        for (int q = 0; q < 4; q++)
        {
            const int qx = (q & 1) << 4;
            const int qy = (q >> 1) << 4;
            const pixel* src16 = src + qy * stride + qx;
            sad16[q] = normalizeSad(blockSadToMean(src16, stride, 4), bitDepth);
            sad8By16[q] = 0;

            for (int b = 0; b < 4; b++)
            {
                const int bx = (b & 1) << 3;
                const int by = (b >> 1) << 3;
                sad8By16[q] += normalizeSad(blockSadToMean(src16 + by * stride + bx, stride, 3), bitDepth);
            }

            f.sad16 += sad16[q];
            f.sad8 += sad8By16[q];
        }

        extractEdges(src, stride, bitDepth, f);
        f.qstepQ8 = qpToQstepQ8(qp);

        /* SAD-domain RD proxy. Constants are deliberately shift/add friendly. */
        const uint32_t lambdaQ8 = qpToLambdaSadQ8(qp);
        const uint32_t split32Bits = 48;
        const uint32_t split16Bits = 24;
        const uint32_t lowBiasBits = 2;
        const uint64_t common16CostQ8 = ((uint64_t)f.sad16 << 8)
                                           + (uint64_t)lambdaQ8 * split32Bits;
        const uint64_t leaf32CostQ8 = (uint64_t)f.sad32 << 8;
        out.highCostQ8 = X265_MIN(leaf32CostQ8, common16CostQ8);

        out.lowCostQ8 = (uint64_t)lambdaQ8 * (split32Bits + lowBiasBits);
        for (int q = 0; q < 4; q++)
        {
            const uint64_t keep16CostQ8 = (uint64_t)sad16[q] << 8;
            const uint64_t split8CostQ8 = ((uint64_t)sad8By16[q] << 8)
                                             + (uint64_t)lambdaQ8 * split16Bits;
            out.lowCostQ8 += X265_MIN(keep16CostQ8, split8CostQ8);
        }

        /*
         * Depth-4 CART fitted from anchor RDO labels over QP 10..51.
         * lowProbability() is intentionally integer-only.  The tunable cutoff
         * is an experiment hook for RD-risk calibration; the final port only
         * needs one constant after BD-rate validation.
         */
        int cutoff = 40;
        const char* cutoffText = getenv("X265_INTRA_LAYER_CUTOFF");
        if (cutoffText && cutoffText[0])
            cutoff = x265_clip3(1, 99, atoi(cutoffText));
        out.layerSet = lowProbability(f) >= (uint32_t)cutoff
                     ? INTRA_LAYER_LOW_16_8
                     : INTRA_LAYER_HIGH_32_16;
        out.only32Probability = intraOnly32Probability(f, qp);
        return out;
    }

private:
    static uint32_t lowProbability(const IntraLayerFeatures& f)
    {
        const uint64_t sad16Q8 = (uint64_t)f.sad16 << 8;
        const uint64_t sad8Q8 = (uint64_t)f.sad8 << 8;

        if (sad16Q8 <= (uint64_t)175 * f.qstepQ8)
        {
            if (f.edge32 <= 4)
            {
                if (sad8Q8 <= (uint64_t)84 * f.qstepQ8)
                    return sad8Q8 <= (uint64_t)59 * f.qstepQ8 ? 1 : 6;
                return f.edge16 <= 5 ? 5 : 29;
            }
            if (sad16Q8 <= (uint64_t)92 * f.qstepQ8)
                return sad16Q8 <= (uint64_t)68 * f.qstepQ8 ? 7 : 25;
            return f.edge4 <= 1182 ? 63 : 43;
        }

        if (f.edge32 == 0)
        {
            if (((uint64_t)f.laplacian << 8) <= (uint64_t)1177 * f.qstepQ8)
                return (uint64_t)(f.gradH + f.gradV) * 1000 <= (uint64_t)1175 * f.sad8 ? 15 : 37;
            return (uint64_t)f.laplacian * 1000 <= (uint64_t)1098 * (f.gradH + f.gradV) ? 24 : 70;
        }

        if (f.edge32 <= 36)
            return f.edge4 <= 1086 ? 90 : 63;

        const uint32_t gain32 = f.sad32 > f.sad16 ? f.sad32 - f.sad16 : 0;
        return ((uint64_t)gain32 << 8) <= (uint64_t)108 * f.qstepQ8 ? 86 : 96;
    }

    static uint32_t blockSadToMean(const pixel* src, intptr_t stride, int log2Size)
    {
        const int size = 1 << log2Size;
        const int countShift = log2Size << 1;
        const uint32_t count = 1U << countShift;
        uint32_t sum = 0;
        const pixel* row = src;

        for (int y = 0; y < size; y++, row += stride)
            for (int x = 0; x < size; x++)
                sum += row[x];

        const int mean = (int)((sum + (count >> 1)) >> countShift);
        uint32_t sad = 0;
        row = src;
        for (int y = 0; y < size; y++, row += stride)
        {
            for (int x = 0; x < size; x++)
            {
                const int diff = (int)row[x] - mean;
                sad += (uint32_t)(diff < 0 ? -diff : diff);
            }
        }
        return sad;
    }

    static void extractEdges(const pixel* src, intptr_t stride, int bitDepth, IntraLayerFeatures& f)
    {
        uint32_t gradH = 0, gradV = 0, lap = 0;
        uint32_t edge4 = 0, edge8 = 0, edge16 = 0, edge32 = 0;
        const int bdShift = X265_MAX(0, bitDepth - 8);

        for (int y = 0; y < 32; y++)
        {
            for (int x = 0; x < 32; x++)
            {
                const int p = (int)src[y * stride + x];
                if (x)
                {
                    int d = p - (int)src[y * stride + x - 1];
                    d = d < 0 ? -d : d;
                    d >>= bdShift;
                    gradH += (uint32_t)d;
                    edge4 += d >= 4;
                    edge8 += d >= 8;
                    edge16 += d >= 16;
                    edge32 += d >= 32;
                }
                if (y)
                {
                    int d = p - (int)src[(y - 1) * stride + x];
                    d = d < 0 ? -d : d;
                    d >>= bdShift;
                    gradV += (uint32_t)d;
                    edge4 += d >= 4;
                    edge8 += d >= 8;
                    edge16 += d >= 16;
                    edge32 += d >= 32;
                }
                if (x && x < 31 && y && y < 31)
                {
                    int h = ((int)src[y * stride + x - 1] + (int)src[y * stride + x + 1]) - (p << 1);
                    int v = ((int)src[(y - 1) * stride + x] + (int)src[(y + 1) * stride + x]) - (p << 1);
                    h = h < 0 ? -h : h;
                    v = v < 0 ? -v : v;
                    lap += (uint32_t)((h + v) >> bdShift);
                }
            }
        }

        f.gradH = gradH;
        f.gradV = gradV;
        f.laplacian = lap;
        f.edge4 = edge4;
        f.edge8 = edge8;
        f.edge16 = edge16;
        f.edge32 = edge32;
    }

    static uint32_t normalizeSad(uint32_t value, int bitDepth)
    {
        const int shift = X265_MAX(0, bitDepth - 8);
        return shift ? (value + (1U << (shift - 1))) >> shift : value;
    }

    static uint32_t qpToLambdaSadQ8(int qp)
    {
        static const uint8_t baseQ8[6] = { 64, 72, 81, 91, 102, 114 };
        const int q = x265_clip3(0, 51, qp);
        return (uint32_t)baseQ8[q % 6] << (q / 6);
    }

    static uint32_t qpToQstepQ8(int qp)
    {
        /* 256 * 2^((QP - 4) / 6), valid for the experiment's QP 10..51. */
        static const uint16_t baseQ8[6] = { 256, 287, 323, 362, 406, 456 };
        const int q = x265_clip3(4, 51, qp) - 4;
        return (uint32_t)baseQ8[q % 6] << (q / 6);
    }
};

}

#endif // X265_INTRA_LAYER_SELECTOR_H
