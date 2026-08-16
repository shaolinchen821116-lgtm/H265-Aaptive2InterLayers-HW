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
    unsigned long tested = 0, mismatches = 0;

    if (argc != 7)
    {
        fprintf(stderr, "usage: %s input.yuv width height qp stats.csv expected_full_ctus\n", argv[0]);
        return 2;
    }
    width = atoi(argv[2]); height = atoi(argv[3]); qp = atoi(argv[4]);
    yuv = fopen(argv[1], "rb"); csv = fopen(argv[5], "rb");
    frame = (uint8_t *)malloc((size_t)width * height * 3 / 2);
    if (!yuv || !csv || !frame ||
        fread(frame, 1, (size_t)width * height * 3 / 2, yuv) != (size_t)width * height * 3 / 2)
        return 3;
    fgets(line, sizeof(line), csv);
    while (fgets(line, sizeof(line), csv))
    {
        char mode[32], selected[16], oracle[16];
        unsigned addr, x, y, leaf32, leaf16, leaf8;
        unsigned sad32, sad16, sad8, gh, gv, lap, e4, e8, e16, e32, qstep;
        unsigned long long high_cost, low_cost, rd_cost;
        unsigned score;
        int row_qp;
        IntraLayerResultC result;
        int fields = sscanf(line,
            "%31[^,],%u,%u,%u,%d,%15[^,],%15[^,],%u,%u,%u,%u,%u,%u,%u,%u,%u,%u,%u,%u,%u,%u,%llu,%llu,%llu,%u",
            mode, &addr, &x, &y, &row_qp, selected, oracle, &leaf32, &leaf16, &leaf8,
            &sad32, &sad16, &sad8, &gh, &gv, &lap, &e4, &e8, &e16, &e32, &qstep,
            &high_cost, &low_cost, &rd_cost, &score);
        if (fields != 25) return 4;
        if (x + 32 > (unsigned)width || y + 32 > (unsigned)height) continue;
        result = intra_layer_select_cascade_y8_32x32(frame + (size_t)y * width + x, width, qp, 94);
        ++tested;
        if (result.only32_score != score ||
            (result.layer_set == INTRA_LAYER_C_ONLY_32) != (strcmp(selected, "only32") == 0))
            ++mismatches;
    }
    fclose(yuv); fclose(csv); free(frame);
    printf("tested=%lu only32_mismatches=%lu\n", tested, mismatches);
    if (tested != strtoul(argv[6], NULL, 10)) return 5;
    return mismatches ? 1 : 0;
}
