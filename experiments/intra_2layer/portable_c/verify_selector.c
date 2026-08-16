#define _CRT_SECURE_NO_WARNINGS
#include "intra_layer_selector.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv)
{
    FILE *yuv, *csv;
    uint8_t *frame;
    char line[4096];
    int width, height, qp;
    unsigned long tested = 0, mismatches = 0, feature_mismatches = 0;

    if (argc != 7)
    {
        fprintf(stderr, "usage: %s input.yuv width height qp stats.csv expected_ctus\n", argv[0]);
        return 2;
    }
    width = atoi(argv[2]);
    height = atoi(argv[3]);
    qp = atoi(argv[4]);
    yuv = fopen(argv[1], "rb");
    csv = fopen(argv[5], "rb");
    frame = (uint8_t *)malloc((size_t)width * height * 3 / 2);
    if (!yuv || !csv || !frame ||
        fread(frame, 1, (size_t)width * height * 3 / 2, yuv) != (size_t)width * height * 3 / 2)
    {
        fprintf(stderr, "failed to open/read inputs\n");
        return 3;
    }
    fgets(line, sizeof(line), csv); /* header */
    while (fgets(line, sizeof(line), csv))
    {
        char mode[32], selected[16], oracle[16];
        unsigned addr, x, y, leaf32, leaf16, leaf8;
        unsigned sad32, sad16, sad8, grad_h, grad_v, lap, edge4, edge8, edge16, edge32, qstep;
        int row_qp;
        IntraLayerResultC r, i420_r;
        uint8_t i420_block[1536];
        const char *actual;
        int row;
        int fields = sscanf(line,
            "%31[^,],%u,%u,%u,%d,%15[^,],%15[^,],%u,%u,%u,%u,%u,%u,%u,%u,%u,%u,%u,%u,%u,%u,",
            mode, &addr, &x, &y, &row_qp, selected, oracle, &leaf32, &leaf16, &leaf8,
            &sad32, &sad16, &sad8, &grad_h, &grad_v, &lap, &edge4, &edge8, &edge16, &edge32, &qstep);
        if (fields != 21)
        {
            fprintf(stderr, "invalid stats row\n");
            return 4;
        }
        if (x + 32 > (unsigned)width || y + 32 > (unsigned)height)
            continue;
        r = intra_layer_select_y8_32x32(frame + (size_t)y * width + x, width, qp);
        for (row = 0; row < 32; ++row)
            memcpy(i420_block + row * 32,
                   frame + (size_t)(y + row) * width + x, 32);
        for (row = 0; row < 16; ++row)
        {
            const size_t chroma_offset = (size_t)(y / 2 + row) * (width / 2) + x / 2;
            memcpy(i420_block + 1024 + row * 16,
                   frame + (size_t)width * height + chroma_offset, 16);
            memcpy(i420_block + 1280 + row * 16,
                   frame + (size_t)width * height * 5 / 4 + chroma_offset, 16);
        }
        i420_r = intra_layer_select_i420_32x32(i420_block, qp);
        actual = r.layer_set == INTRA_LAYER_C_LOW_16_8 ? "low" : "high";
        ++tested;
        if (strcmp(actual, selected) || i420_r.layer_set != r.layer_set ||
            i420_r.low_score != r.low_score)
            ++mismatches;
        if (r.features.sad32 != sad32 || r.features.sad16 != sad16 || r.features.sad8 != sad8 ||
            r.features.grad_h != grad_h || r.features.grad_v != grad_v || r.features.laplacian != lap ||
            r.features.edge4 != edge4 || r.features.edge8 != edge8 || r.features.edge16 != edge16 ||
            r.features.edge32 != edge32 || r.features.qstep_q8 != qstep ||
            memcmp(&i420_r.features, &r.features, sizeof(r.features)) != 0)
            ++feature_mismatches;
    }
    fclose(yuv);
    fclose(csv);
    free(frame);
    printf("tested=%lu decision_mismatches=%lu feature_mismatches=%lu\n",
           tested, mismatches, feature_mismatches);
    if (tested != strtoul(argv[6], NULL, 10)) return 5;
    return mismatches || feature_mismatches ? 1 : 0;
}
