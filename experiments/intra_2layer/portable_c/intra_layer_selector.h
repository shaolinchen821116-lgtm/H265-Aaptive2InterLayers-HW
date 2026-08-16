#ifndef INTRA_LAYER_SELECTOR_C_H
#define INTRA_LAYER_SELECTOR_C_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef enum IntraLayerSetC
{
    INTRA_LAYER_C_HIGH_32_16 = 0,
    INTRA_LAYER_C_LOW_16_8 = 1,
    INTRA_LAYER_C_ONLY_32 = 2
} IntraLayerSetC;

typedef struct IntraLayerFeaturesC
{
    uint32_t sad32;
    uint32_t sad16;
    uint32_t sad8;
    uint32_t grad_h;
    uint32_t grad_v;
    uint32_t laplacian;
    uint32_t edge4;
    uint32_t edge8;
    uint32_t edge16;
    uint32_t edge32;
    uint32_t qstep_q8;
} IntraLayerFeaturesC;

typedef struct IntraLayerResultC
{
    IntraLayerSetC layer_set;
    uint32_t low_score;
    uint32_t only32_score;
    IntraLayerFeaturesC features;
} IntraLayerResultC;

/*
 * Select from the 32x32 original 8-bit luma block.  y_stride is measured in
 * bytes and may be the source picture width.  QP is clipped to [4, 51].
 */
IntraLayerResultC intra_layer_select_y8_32x32(
    const uint8_t *y, ptrdiff_t y_stride, int qp);

/*
 * Convenience entry for one tightly packed 32x32 I420 block:
 *   bytes [0,1023]     = Y 32x32
 *   bytes [1024,1279]  = U 16x16 (ignored)
 *   bytes [1280,1535]  = V 16x16 (ignored)
 */
IntraLayerResultC intra_layer_select_i420_32x32(
    const uint8_t i420_block[1536], int qp);

/* Three-output cascade: ONLY32 first, otherwise the existing HIGH/LOW tree. */
IntraLayerResultC intra_layer_select_cascade_y8_32x32(
    const uint8_t *y, ptrdiff_t y_stride, int qp, uint32_t only32_cutoff);

IntraLayerResultC intra_layer_select_cascade_i420_32x32(
    const uint8_t i420_block[1536], int qp, uint32_t only32_cutoff);

#ifdef __cplusplus
}
#endif

#endif
