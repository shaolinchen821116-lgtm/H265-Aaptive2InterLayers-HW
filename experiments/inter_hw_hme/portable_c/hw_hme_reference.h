#ifndef HW_HME_REFERENCE_H
#define HW_HME_REFERENCE_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct hw_hme_mv
{
    int32_t x;
    int32_t y;
} hw_hme_mv;

typedef struct hw_hme_plane8
{
    const uint8_t* data;
    ptrdiff_t stride;
    int width;
    int height;
} hw_hme_plane8;

typedef struct hw_hme_config
{
    int pme_range_x_ds;
    int pme_range_y_ds;
    int ime_range_x_full;
    int ime_range_y_full;
    unsigned pme_sad_shift;
    int pme_cost_mode;          /* 0: legacy product, 1: adaptive additive */
    uint32_t pme_rate_scale_q8;
    uint16_t pme_texture_low;
    uint16_t pme_texture_high;
    uint16_t pme_texture_weight_q8[3];
    int pme_attractor;          /* 0: zero, 1: AMVP, 2: min(zero, AMVP+flag) */
} hw_hme_config;

typedef uint32_t (*hw_hme_mvd_bits_fn)(void* opaque, hw_hme_mv mv_qpel,
                                      hw_hme_mv predictor_qpel);
typedef uint32_t (*hw_hme_mvd_cost_fn)(void* opaque, int qp,
                                      hw_hme_mv mv_qpel,
                                      hw_hme_mv predictor_qpel);
typedef uint32_t (*hw_hme_qpel_sad_fn)(void* opaque, hw_hme_mv mv_qpel);

typedef struct hw_hme_callbacks
{
    void* opaque;
    hw_hme_mvd_bits_fn mvd_bits;
    hw_hme_mvd_cost_fn mvd_cost;
    hw_hme_qpel_sad_fn qpel_sad;
} hw_hme_callbacks;

typedef struct hw_hme_input
{
    hw_hme_plane8 current_ds4;
    hw_hme_plane8 reference_ds4;
    hw_hme_plane8 current_full;
    hw_hme_plane8 reference_full;
    int block_x_full;
    int block_y_full;
    int block_size;
    int qp;
    hw_hme_mv amvp_qpel;
    hw_hme_mv mv_min_full;
    hw_hme_mv mv_max_full;
} hw_hme_input;

typedef struct hw_hme_result
{
    hw_hme_mv pme_mv_ds;
    hw_hme_mv ime_center_full;
    hw_hme_mv ime_mv_full;
    hw_hme_mv fme_mv_qpel;
    uint32_t pme_sad;
    uint32_t pme_bits;
    uint64_t pme_cost;
    uint32_t ime_sad;
    uint32_t ime_cost;
    uint32_t fme_sad;
    uint32_t fme_cost;
    uint32_t pme_candidates;
    uint32_t ime_candidates;
    uint32_t fme_candidates;
    uint32_t pme_activity;
    uint32_t pme_rate_weight_q8;
    uint8_t pme_texture_class;
    uint8_t pme_used_amvp;
    uint8_t ime_boundary;
} hw_hme_result;

typedef enum hw_hme_inter_layer_set
{
    HW_HME_INTER_HIGH_32_16 = 0,
    HW_HME_INTER_LOW_16_8 = 1,
    HW_HME_INTER_ONLY_32 = 2
} hw_hme_inter_layer_set;

typedef struct hw_hme_inter_layer_features
{
    uint32_t ime_sad_per_pixel_q8;
    uint32_t pme_to_ime_l1;
    uint32_t ime_mvd_qpel_l1;
    uint32_t ime_mv_fullpel_l1;
    uint32_t pme_activity;
    uint8_t ime_boundary;
} hw_hme_inter_layer_features;

typedef struct hw_hme_inter_layer_decision
{
    hw_hme_inter_layer_set layer_set;
    hw_hme_inter_layer_features features;
    uint32_t only32_probability;
    uint32_t low2_probability;
} hw_hme_inter_layer_decision;

enum { HW_HME_INTER_MS_FEATURE_COUNT = 29 };

/* Frozen mode-8 feature vector. Index order is identical to the generated
 * CART header and to INTERLAYERMS logs; see the training documentation. */
typedef struct hw_hme_inter_scale_features
{
    uint32_t value[HW_HME_INTER_MS_FEATURE_COUNT];
    uint8_t valid;
} hw_hme_inter_scale_features;

/* Fills the final experiment defaults: PME [-32,32]x[-28,28] on ds4,
 * IME [-12,12]^2, adaptive additive cost, Q8 scale 256, gradient
 * thresholds 8/24, weights 256/160/96, and AMVP attractor. */
void hw_hme_config_default(hw_hme_config* config);

/* 8-bit x265 motion-estimation lambda in Q8 for QP 0..51. */
uint32_t hw_hme_default_lambda_q8(int qp);

/* Generates the same phase-zero two-stage 2x downsample used by the x265
 * integration. Width and height must be multiples of four. half_scratch must
 * hold (width / 2) * (height / 2) bytes. */
int hw_hme_downsample4(const uint8_t* src, ptrdiff_t src_stride,
                       int width, int height, uint8_t* half_scratch,
                       ptrdiff_t half_stride, uint8_t* dst4,
                       ptrdiff_t dst4_stride);

/* Runs PME -> IME -> FME. The callbacks isolate entropy-bit estimation and
 * HEVC quarter-pel interpolation, which are platform-specific. */
int hw_hme_search(const hw_hme_config* config, const hw_hme_input* input,
                  const hw_hme_callbacks* callbacks, hw_hme_result* result);

/* Hardware-oriented CU32 decision. The function first applies the conservative
 * ONLY32 gate, then falls back to the existing HIGH(32/16) versus LOW(16/8)
 * integer tree. The result and AMVP must come from the CU32 IME probe. */
int hw_hme_select_inter_layers(const hw_hme_result* result,
                               hw_hme_mv amvp_qpel, int qp,
                               int low2_probability_cutoff,
                               int only32_probability_cutoff,
                               hw_hme_inter_layer_decision* decision);

/* Aggregates one CU32, four CU16 and sixteen CU8 PME/IME-only results. All
 * divisions are fixed /4 or /16 rounded shifts. The probe order is raster:
 * CU16[0..3], and four raster CU8 children per CU16. AMVP is the common CU32
 * predictor used by all 20 child probes. */
int hw_hme_build_inter_scale_features(
    const hw_hme_result* root, hw_hme_mv root_amvp_qpel, int qp,
    const hw_hme_result probe16[4], const hw_hme_result probe8[16],
    int ime_range_x, int ime_range_y, hw_hme_inter_scale_features* features);

/* Frozen depth-7 cost-sensitive CART. A cutoff of 45 is the validated
 * operating point. This selector never emits ONLY32. */
int hw_hme_select_inter_layers_multiscale(
    const hw_hme_inter_scale_features* features, int probability_cutoff,
    hw_hme_inter_layer_decision* decision);

/* Small, deterministic Exp-Golomb-style fallback for prototypes. Production
 * ports should connect their codec's exact MVD bit estimator instead. */
uint32_t hw_hme_default_mvd_bits(void* opaque, hw_hme_mv mv_qpel,
                                hw_hme_mv predictor_qpel);

#ifdef __cplusplus
}
#endif
#endif
