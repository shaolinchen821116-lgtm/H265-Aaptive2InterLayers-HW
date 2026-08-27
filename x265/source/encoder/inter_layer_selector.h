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
#include "inter_only32_gate_model.h"
#include "inter_multiscale_gate_model.h"
#include "inter_sum_cost_gate_model.h"

namespace X265_NS {

enum HardwareInterLayerSet
{
    HW_INTER_LAYER_HIGH_32_16 = 0,
    HW_INTER_LAYER_LOW_16_8 = 1,
    HW_INTER_LAYER_ONLY_32 = 2
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

enum HardwareInterMsFeatureIndex
{
    HW_INTER_MS_QP = 0,
    HW_INTER_MS_SAD32_Q8,
    HW_INTER_MS_REFINE32_L1,
    HW_INTER_MS_MVD32_QPEL_L1,
    HW_INTER_MS_MV32_FULLPEL_L1,
    HW_INTER_MS_ACTIVITY32,
    HW_INTER_MS_BOUNDARY32,
    HW_INTER_MS_SAD16_MEAN_Q8,
    HW_INTER_MS_SAD16_RANGE_Q8,
    HW_INTER_MS_SAD16_MAD_Q8,
    HW_INTER_MS_SAD8_MEAN_Q8,
    HW_INTER_MS_SAD8_RANGE_Q8,
    HW_INTER_MS_SAD8_MAD_Q8,
    HW_INTER_MS_SAD_GAIN32_TO16_Q8,
    HW_INTER_MS_SAD_GAIN16_TO8_Q8,
    HW_INTER_MS_SAD_GAIN16_TO8_MAX_Q8,
    HW_INTER_MS_MV16_ROOT_MEAN_L1,
    HW_INTER_MS_MV16_ROOT_MAX_L1,
    HW_INTER_MS_MV16_SPAN_L1,
    HW_INTER_MS_MV8_PARENT_MEAN_L1,
    HW_INTER_MS_MV8_PARENT_MAX_L1,
    HW_INTER_MS_MV8_ROOT_MEAN_L1,
    HW_INTER_MS_MV8_ROOT_MAX_L1,
    HW_INTER_MS_MV8_SPAN_L1,
    HW_INTER_MS_ACTIVITY16_MEAN,
    HW_INTER_MS_ACTIVITY16_RANGE,
    HW_INTER_MS_ACTIVITY8_MEAN,
    HW_INTER_MS_ACTIVITY8_RANGE,
    HW_INTER_MS_BOUNDARY_COUNT,
    HW_INTER_MS_FEATURE_COUNT
};

/* Multi-scale pre-decision features. All divisions used to construct these
 * fields are by 4 or 16, so the hardware data path needs only add/abs/min/max
 * and shifts. SAD fields are Q8 per source pixel at every block size. */
struct HardwareInterScaleFeatures
{
    HardwareInterLayerFeatures root;
    uint32_t qp;
    uint32_t sad16MeanQ8;
    uint32_t sad16RangeQ8;
    uint32_t sad16MadQ8;
    uint32_t sad8MeanQ8;
    uint32_t sad8RangeQ8;
    uint32_t sad8MadQ8;
    uint32_t sadGain32To16Q8;
    uint32_t sadGain16To8Q8;
    uint32_t sadGain16To8MaxQ8;
    uint32_t mv16RootMeanL1;
    uint32_t mv16RootMaxL1;
    uint32_t mv16SpanL1;
    uint32_t mv8ParentMeanL1;
    uint32_t mv8ParentMaxL1;
    uint32_t mv8RootMeanL1;
    uint32_t mv8RootMaxL1;
    uint32_t mv8SpanL1;
    uint32_t activity16Mean;
    uint32_t activity16Range;
    uint32_t activity8Mean;
    uint32_t activity8Range;
    uint32_t boundaryCount;
    uint32_t sqrtLambdaQ8;
    uint32_t splitBits32;
    uint32_t splitBits8To32;
    uint32_t rootMvdBits;
    uint64_t cost8Group[4];
    uint64_t cost8SumGroup[4];
    uint64_t cost32;
    uint64_t cost8To32;
    uint64_t cost8SumTo32;
    uint8_t valid;

    HardwareInterScaleFeatures() { memset(this, 0, sizeof(*this)); }

    void toArray(uint32_t out[HW_INTER_MS_FEATURE_COUNT]) const
    {
        out[HW_INTER_MS_QP] = qp;
        out[HW_INTER_MS_SAD32_Q8] = root.imeSadPerPixelQ8;
        out[HW_INTER_MS_REFINE32_L1] = root.pmeToImeL1;
        out[HW_INTER_MS_MVD32_QPEL_L1] = root.imeMvdQPelL1;
        out[HW_INTER_MS_MV32_FULLPEL_L1] = root.imeMvFullPelL1;
        out[HW_INTER_MS_ACTIVITY32] = root.pmeActivity;
        out[HW_INTER_MS_BOUNDARY32] = root.imeBoundary;
        out[HW_INTER_MS_SAD16_MEAN_Q8] = sad16MeanQ8;
        out[HW_INTER_MS_SAD16_RANGE_Q8] = sad16RangeQ8;
        out[HW_INTER_MS_SAD16_MAD_Q8] = sad16MadQ8;
        out[HW_INTER_MS_SAD8_MEAN_Q8] = sad8MeanQ8;
        out[HW_INTER_MS_SAD8_RANGE_Q8] = sad8RangeQ8;
        out[HW_INTER_MS_SAD8_MAD_Q8] = sad8MadQ8;
        out[HW_INTER_MS_SAD_GAIN32_TO16_Q8] = sadGain32To16Q8;
        out[HW_INTER_MS_SAD_GAIN16_TO8_Q8] = sadGain16To8Q8;
        out[HW_INTER_MS_SAD_GAIN16_TO8_MAX_Q8] = sadGain16To8MaxQ8;
        out[HW_INTER_MS_MV16_ROOT_MEAN_L1] = mv16RootMeanL1;
        out[HW_INTER_MS_MV16_ROOT_MAX_L1] = mv16RootMaxL1;
        out[HW_INTER_MS_MV16_SPAN_L1] = mv16SpanL1;
        out[HW_INTER_MS_MV8_PARENT_MEAN_L1] = mv8ParentMeanL1;
        out[HW_INTER_MS_MV8_PARENT_MAX_L1] = mv8ParentMaxL1;
        out[HW_INTER_MS_MV8_ROOT_MEAN_L1] = mv8RootMeanL1;
        out[HW_INTER_MS_MV8_ROOT_MAX_L1] = mv8RootMaxL1;
        out[HW_INTER_MS_MV8_SPAN_L1] = mv8SpanL1;
        out[HW_INTER_MS_ACTIVITY16_MEAN] = activity16Mean;
        out[HW_INTER_MS_ACTIVITY16_RANGE] = activity16Range;
        out[HW_INTER_MS_ACTIVITY8_MEAN] = activity8Mean;
        out[HW_INTER_MS_ACTIVITY8_RANGE] = activity8Range;
        out[HW_INTER_MS_BOUNDARY_COUNT] = boundaryCount;
    }
};

struct HardwareInterLayerDecision
{
    HardwareInterLayerSet layerSet;
    HardwareInterLayerFeatures features;
    HardwareInterScaleFeatures scaleFeatures;
    uint32_t only32Probability;
    uint32_t lowProbability;

    HardwareInterLayerDecision()
        : layerSet(HW_INTER_LAYER_LOW_16_8), only32Probability(0),
          lowProbability(0) {}
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
    out.only32Probability = 0;
    out.layerSet = HW_INTER_LAYER_LOW_16_8; /* fail-safe for missing probe */
    if (!out.features.valid)
        return out;

    out.only32Probability = hwInterOnly32ModelProbability(
        qp, out.features.imeSadPerPixelQ8, out.features.pmeToImeL1,
        out.features.imeMvdQPelL1, out.features.imeMvFullPelL1,
        out.features.pmeActivity, out.features.imeBoundary);

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
    out.lowProbability = lowProbability;
    return out;
}

static inline HardwareInterLayerDecision hwSelectInterLayersMultiscale(
    const HardwareInterScaleFeatures& features, int probabilityCutoff)
{
    HardwareInterLayerDecision out;
    out.features = features.root;
    out.scaleFeatures = features;
    if (!features.valid)
        return out;
    uint32_t values[HW_INTER_MS_FEATURE_COUNT];
    features.toArray(values);
    out.lowProbability = hwInterMultiscaleLowProbability(values);
    out.layerSet = out.lowProbability >= (uint32_t)probabilityCutoff
                 ? HW_INTER_LAYER_LOW_16_8
                 : HW_INTER_LAYER_HIGH_32_16;
    return out;
}

/* Cost-hierarchy baseline requested for mode 9. The 8x8 path is built by
 * taking min(J8) within each group of four children, multiplying by four,
 * then summing the four CU16 regions. Split signaling is already included in
 * cost32/cost8To32. A strict CU32 win selects HIGH; a tie selects LOW. */
static inline HardwareInterLayerDecision hwSelectInterLayersHierarchyCost(
    const HardwareInterScaleFeatures& features)
{
    HardwareInterLayerDecision out;
    out.features = features.root;
    out.scaleFeatures = features;
    if (!features.valid)
        return out;
    const bool low = features.cost8To32 <= features.cost32;
    out.lowProbability = low ? 100u : 0u;
    out.layerSet = low ? HW_INTER_LAYER_LOW_16_8
                       : HW_INTER_LAYER_HIGH_32_16;
    return out;
}

/* Corrected hierarchy-cost baseline. Unlike mode 9, this path preserves the
 * measured J8 of every child and adds all sixteen costs. This removes the
 * optimistic 4 * min(J8) approximation while retaining the same Q8 lambda
 * rate term and five split bits. */
static inline HardwareInterLayerDecision hwSelectInterLayersHierarchySumCost(
    const HardwareInterScaleFeatures& features)
{
    HardwareInterLayerDecision out;
    out.features = features.root;
    out.scaleFeatures = features;
    if (!features.valid)
        return out;
    const bool low = features.cost8SumTo32 <= features.cost32;
    out.lowProbability = low ? 100u : 0u;
    out.layerSet = low ? HW_INTER_LAYER_LOW_16_8
                       : HW_INTER_LAYER_HIGH_32_16;
    return out;
}

static inline uint32_t hwInterSumCostRatioBin(uint64_t cost8, uint64_t cost32)
{
    if (cost8 * 4 <= cost32 * 3) return 0;
    if (cost8 * 8 <= cost32 * 7) return 1;
    if (cost8 <= cost32) return 2;
    if (cost8 * 8 <= cost32 * 9) return 3;
    if (cost8 * 4 <= cost32 * 5) return 4;
    if (cost8 * 2 <= cost32 * 3) return 5;
    return 6;
}

/* Mode 11: corrected sum-cost is the forced first decision; the generated
 * child tree corrects it with SAD hierarchy, activity/texture and MV
 * consistency. All normalization uses shifts and integer arithmetic. */
static inline HardwareInterLayerDecision hwSelectInterLayersSumCostAdaptive(
    const HardwareInterScaleFeatures& features, int probabilityCutoff)
{
    HardwareInterLayerDecision out;
    out.features = features.root;
    out.scaleFeatures = features;
    if (!features.valid)
        return out;
    uint32_t values[HW_INTER_MS_FEATURE_COUNT + 11];
    features.toArray(values);
    const uint64_t groupMean = (features.cost8SumGroup[0] +
                                features.cost8SumGroup[1] +
                                features.cost8SumGroup[2] +
                                features.cost8SumGroup[3] + 2) >> 2;
    uint64_t groupMin = features.cost8SumGroup[0];
    uint64_t groupMax = groupMin;
    uint64_t groupMad = 0;
    for (uint32_t i = 0; i < 4; i++)
    {
        groupMin = X265_MIN(groupMin, features.cost8SumGroup[i]);
        groupMax = X265_MAX(groupMax, features.cost8SumGroup[i]);
        groupMad += features.cost8SumGroup[i] > groupMean
                  ? features.cost8SumGroup[i] - groupMean
                  : groupMean - features.cost8SumGroup[i];
    }
    const uint32_t base = HW_INTER_MS_FEATURE_COUNT;
    values[base + 0] = features.cost8SumTo32 <= features.cost32;
    values[base + 1] = hwInterSumCostRatioBin(features.cost8SumTo32,
                                              features.cost32);
    values[base + 2] = (uint32_t)((features.cost32 + 2) >> 2);
    values[base + 3] = (uint32_t)((features.cost8SumTo32 + 2) >> 2);
    values[base + 4] = (uint32_t)(((features.cost8SumTo32 > features.cost32
                         ? features.cost8SumTo32 - features.cost32
                         : features.cost32 - features.cost8SumTo32) + 2) >> 2);
    values[base + 5] = (uint32_t)groupMean;
    values[base + 6] = (uint32_t)(groupMax - groupMin);
    values[base + 7] = (uint32_t)((groupMad + 2) >> 2);
    values[base + 8] = (uint32_t)((features.cost8To32 + 2) >> 2);
    values[base + 9] = (uint32_t)(((features.cost8SumTo32 > features.cost8To32
                         ? features.cost8SumTo32 - features.cost8To32 : 0) + 2) >> 2);
    values[base + 10] = features.sqrtLambdaQ8;
    out.lowProbability = hwInterSumCostLowProbability(values);
    const bool low = out.lowProbability >= (uint32_t)probabilityCutoff;
    out.layerSet = low ? HW_INTER_LAYER_LOW_16_8
                       : HW_INTER_LAYER_HIGH_32_16;
    return out;
}

}

#endif // X265_INTER_LAYER_SELECTOR_H
