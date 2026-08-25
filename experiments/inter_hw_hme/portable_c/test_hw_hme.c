#include "hw_hme_reference.h"

#include <stdio.h>
#include <string.h>

#define CHECK(condition) do { \
    if (!(condition)) { \
        fprintf(stderr, "CHECK failed at line %d: %s\n", __LINE__, #condition); \
        return 1; \
    } \
} while (0)

enum { W = 320, H = 288, HALF_W = W / 2, HALF_H = H / 2, DS_W = W / 4, DS_H = H / 4 };
static uint8_t current[W * H], reference[W * H];
static uint8_t current_half[HALF_W * HALF_H], reference_half[HALF_W * HALF_H];
static uint8_t current_ds[DS_W * DS_H], reference_ds[DS_W * DS_H];

typedef struct test_context
{
    hw_hme_plane8 current;
    hw_hme_plane8 reference;
    int x;
    int y;
    int size;
} test_context;

static uint32_t mv_cost(void* opaque, int qp, hw_hme_mv mv, hw_hme_mv predictor)
{
    uint32_t bits = hw_hme_default_mvd_bits(opaque, mv, predictor);
    return bits * (uint32_t)(qp + 4) / 8;
}

static uint32_t qpel_sad(void* opaque, hw_hme_mv mv)
{
    test_context* c = (test_context*)opaque;
    int ix = mv.x >= 0 ? (mv.x + 2) / 4 : -((-mv.x + 2) / 4);
    int iy = mv.y >= 0 ? (mv.y + 2) / 4 : -((-mv.y + 2) / 4);
    uint32_t sad = 0;
    int x, y;
    const uint8_t* a = c->current.data + c->y * c->current.stride + c->x;
    const uint8_t* b = c->reference.data + (c->y + iy) * c->reference.stride + c->x + ix;
    for (y = 0; y < c->size; ++y)
        for (x = 0; x < c->size; ++x)
            sad += (uint32_t)(a[y * c->current.stride + x] > b[y * c->reference.stride + x]
                ? a[y * c->current.stride + x] - b[y * c->reference.stride + x]
                : b[y * c->reference.stride + x] - a[y * c->current.stride + x]);
    return sad;
}

int main(void)
{
    hw_hme_config config;
    hw_hme_input input;
    hw_hme_callbacks callbacks;
    hw_hme_result result;
    hw_hme_result probe16[4], probe8[16];
    hw_hme_inter_layer_decision layer_decision;
    hw_hme_inter_scale_features scale_features;
    test_context context;
    int i;
    hw_hme_config_default(&config);
    for (i = 0; i < W * H; ++i)
        current[i] = reference[i] = (uint8_t)((i * 37 + i / W * 13) & 255);
    CHECK(hw_hme_downsample4(current, W, W, H, current_half, HALF_W,
                             current_ds, DS_W) == 0);
    CHECK(hw_hme_downsample4(reference, W, W, H, reference_half, HALF_W,
                             reference_ds, DS_W) == 0);
    memset(&input, 0, sizeof(input));
    input.current_ds4 = (hw_hme_plane8){ current_ds, DS_W, DS_W, DS_H };
    input.reference_ds4 = (hw_hme_plane8){ reference_ds, DS_W, DS_W, DS_H };
    input.current_full = (hw_hme_plane8){ current, W, W, H };
    input.reference_full = (hw_hme_plane8){ reference, W, W, H };
    input.block_x_full = 144;
    input.block_y_full = 128;
    input.block_size = 32;
    input.qp = 32;
    input.mv_min_full = (hw_hme_mv){ -128, -112 };
    input.mv_max_full = (hw_hme_mv){ 128, 112 };
    context.current = input.current_full;
    context.reference = input.reference_full;
    context.x = input.block_x_full;
    context.y = input.block_y_full;
    context.size = input.block_size;
    callbacks.opaque = &context;
    callbacks.mvd_bits = hw_hme_default_mvd_bits;
    callbacks.mvd_cost = mv_cost;
    callbacks.qpel_sad = qpel_sad;
    CHECK(hw_hme_search(&config, &input, &callbacks, &result) == 0);
    CHECK(result.pme_mv_ds.x == 0 && result.pme_mv_ds.y == 0);
    CHECK(result.ime_center_full.x == 0 && result.ime_center_full.y == 0);
    CHECK(result.ime_mv_full.x == 0 && result.ime_mv_full.y == 0);
    CHECK(result.fme_mv_qpel.x == 0 && result.fme_mv_qpel.y == 0);
    CHECK(result.pme_candidates == 65u * 57u);
    CHECK(result.ime_candidates == 25u * 25u);
    CHECK(result.fme_candidates == 17u);
    CHECK(result.pme_used_amvp == 1u);
    CHECK(result.pme_rate_weight_q8 > 0u);
    CHECK(hw_hme_select_inter_layers(&result, input.amvp_qpel, input.qp,
                                     50, 92, &layer_decision) == 0);
    CHECK(layer_decision.layer_set >= HW_HME_INTER_HIGH_32_16 &&
          layer_decision.layer_set <= HW_HME_INTER_ONLY_32);
    CHECK(layer_decision.only32_probability <= 100u);
    for (i = 0; i < 4; ++i)
        probe16[i] = result;
    for (i = 0; i < 16; ++i)
        probe8[i] = result;
    /* Adjust raw SAD units to the child block sizes. The all-zero motion case
     * also provides a deterministic aggregation and inference smoke test. */
    CHECK(hw_hme_build_inter_scale_features(&result, input.amvp_qpel,
                                             input.qp, probe16, probe8,
                                             12, 12, &scale_features) == 0);
    CHECK(scale_features.valid == 1u);
    CHECK(scale_features.value[0] == 32u);
    CHECK(hw_hme_select_inter_layers_multiscale(&scale_features, 45,
                                                 &layer_decision) == 0);
    CHECK(layer_decision.low2_probability <= 100u);
    CHECK(layer_decision.layer_set == HW_HME_INTER_HIGH_32_16 ||
          layer_decision.layer_set == HW_HME_INTER_LOW_16_8);
    config.pme_cost_mode = 0;
    config.pme_attractor = 0;
    CHECK(hw_hme_search(&config, &input, &callbacks, &result) == 0);
    CHECK(result.pme_mv_ds.x == 0 && result.pme_mv_ds.y == 0);
    printf("portable C HW-HME test passed; candidates=%u/%u/%u\n",
           result.pme_candidates, result.ime_candidates, result.fme_candidates);
    return 0;
}
