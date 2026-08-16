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
} hw_hme_result;

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

/* Small, deterministic Exp-Golomb-style fallback for prototypes. Production
 * ports should connect their codec's exact MVD bit estimator instead. */
uint32_t hw_hme_default_mvd_bits(void* opaque, hw_hme_mv mv_qpel,
                                hw_hme_mv predictor_qpel);

#ifdef __cplusplus
}
#endif
#endif
