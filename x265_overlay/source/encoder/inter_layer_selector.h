/****************************************************************************
 * Hardware-oriented P-frame CU-layer selector.
 *
 * Input is the CU32 IME result only (plus frame QP for threshold tracking).
 * HIGH evaluates CU32/CU16; LOW evaluates CU16/CU8. Arithmetic is integer
 * and uses only comparisons, absolute differences, shifts, and additions.
 ****************************************************************************/

#ifndef X265_INTER_LAYER_SELECTOR_H
#define X265_INTER_LAYER_SELECTOR_H

#include "common.h"
#include "search.h"

namespace X265_NS {

enum HardwareInterLayerSet
{
    HW_INTER_LAYER_HIGH_32_16 = 0,
    HW_INTER_LAYER_LOW_16_8 = 1
};

struct HardwareInterLayerFeatures
{
    uint32_t imeSadPerPixelQ8;
    uint32_t pmeToImeL1;
    uint32_t imeMvdQPelL1;
    uint32_t imeMvFullPelL1;
    uint32_t pmeActivity;
    uint8_t imeBoundary;
    uint8_t valid;

    HardwareInterLayerFeatures() { memset(this, 0, sizeof(*this)); }
};

struct HardwareInterLayerDecision
{
    HardwareInterLayerSet layerSet;
    HardwareInterLayerFeatures features;
};

static inline HardwareInterLayerFeatures hwInterLayerFeatures(const MotionData& me)
{
    HardwareInterLayerFeatures f;
    f.valid = me.hwValid;
    if (!f.valid)
        return f;

    /* CU32 has 1024 pixels: SAD * 256 / 1024 == SAD >> 2. */
    f.imeSadPerPixelQ8 = (me.hwImeSad + 2) >> 2;
    f.pmeToImeL1 = abs(me.hwImeMvFullPel.x - me.hwImeCenterFullPel.x) +
                   abs(me.hwImeMvFullPel.y - me.hwImeCenterFullPel.y);
    const MV imeQPel = me.hwImeMvFullPel * 4;
    f.imeMvdQPelL1 = abs(imeQPel.x - me.mvp.x) + abs(imeQPel.y - me.mvp.y);
    f.imeMvFullPelL1 = abs(me.hwImeMvFullPel.x) + abs(me.hwImeMvFullPel.y);
    f.pmeActivity = me.hwPmeActivity;
    f.imeBoundary = me.hwImeBoundary;
    return f;
}

static inline HardwareInterLayerDecision hwSelectInterLayers(
    const MotionData& me, int qp, int sadBaseQ8, int sadSlopeQ8,
    int refineThreshold, int probabilityCutoff)
{
    HardwareInterLayerDecision out;
    out.features = hwInterLayerFeatures(me);
    out.layerSet = HW_INTER_LAYER_LOW_16_8; /* fail-safe for missing probe */
    if (!out.features.valid)
        return out;

    (void)sadBaseQ8;
    (void)sadSlopeQ8;
    (void)refineThreshold;

    /* Depth-4 weighted CART trained on 448,800 Class-B CTUs. Labels come
     * from the complete 32/16/8 RDO result: any selected CU8 => LOW;
     * otherwise HIGH. Leaf values are integer low-layer probabilities. */
    const uint32_t sad = out.features.imeSadPerPixelQ8;
    const uint32_t mv = out.features.imeMvFullPelL1;
    uint32_t lowProbability;
    if (qp <= 29)
    {
        if (sad <= 665)
        {
            if (qp <= 24)
                lowProbability = mv <= 2 ? 79 : 67;
            else
                lowProbability = sad <= 565 ? 25 : 41;
        }
        else if (mv <= 4)
            lowProbability = sad <= 959 ? 80 : 93;
        else
            lowProbability = qp <= 24 ? 81 : 60;
    }
    else if (sad <= 1184)
    {
        if (sad <= 781)
            lowProbability = qp <= 34 ? 18 : 10;
        else
            lowProbability = qp <= 34 ? 46 : 20;
    }
    else if (qp <= 34)
        lowProbability = mv <= 7 ? 82 : 58;
    else
        lowProbability = sad <= 1633 ? 38 : 64;

    out.layerSet = lowProbability >= (uint32_t)probabilityCutoff
                 ? HW_INTER_LAYER_LOW_16_8
                 : HW_INTER_LAYER_HIGH_32_16;
    return out;
}

}

#endif // X265_INTER_LAYER_SELECTOR_H
