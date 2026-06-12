// Filter candidate seeds for two viable Ocean Monuments within a maximum distance.
// Uses cubiomes. This is a practical second-stage filter after slime prefilter.
//
// Build example:
//   gcc -O3 -march=native -std=c11 -Wall -Wextra -I../../tools/cubiomes \
//       -o ocean_monument_filter ocean_monument_filter.c ../../tools/cubiomes/libcubiomes.a -lm

#include <ctype.h>
#include <errno.h>
#include <inttypes.h>
#include <math.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "finders.h"
#include "generator.h"

typedef struct {
    int x;
    int z;
} IPos;

typedef struct {
    int rx;
    int rz;
    int x;
    int z;
} MonumentAttempt;

static long parse_long_arg(const char *s, const char *name) {
    errno = 0;
    char *end = NULL;
    long v = strtol(s, &end, 10);
    if (errno || !end || *end) {
        fprintf(stderr, "Invalid %s: %s\n", name, s);
        exit(2);
    }
    return v;
}

static int64_t parse_seed_from_csv_line(const char *line) {
    // The first column is seed. It may be signed decimal.
    errno = 0;
    char *end = NULL;
    int64_t seed = strtoll(line, &end, 10);
    if (errno || end == line || (*end && *end != ',' && *end != '\n' && *end != '\r')) {
        fprintf(stderr, "Could not parse seed from line: %.120s\n", line);
        exit(2);
    }
    return seed;
}

static void usage(const char *argv0) {
    fprintf(stderr,
        "Usage: %s --in candidates.csv --out monuments.csv [options]\n"
        "Options:\n"
        "  --radius-blocks N       require monument positions in square +/-N from origin (default 10000)\n"
        "  --circle                require monument positions inside Euclidean radius N\n"
        "  --max-distance N        require pair distance <= N blocks (default 256)\n"
        "  --mc newest|1_21|1_20   cubiomes version approximation (default newest)\n"
        "  --limit N               process at most N candidate rows (default 0 = all)\n",
        argv0);
}

static int parse_mc(const char *s) {
    if (!s || !*s || !strcmp(s, "newest") || !strcmp(s, "26.2") || !strcmp(s, "26.2-pre1")) return MC_NEWEST;
    if (!strcmp(s, "1_21") || !strcmp(s, "1.21")) return MC_1_21;
    if (!strcmp(s, "1_20") || !strcmp(s, "1.20")) return MC_1_20;
    fprintf(stderr, "Unsupported --mc %s; use newest, 1_21, or 1_20.\n", s);
    exit(2);
}

static bool find_double_monument(uint64_t seed, int mc, int radius, int maxdist, bool circle, IPos *a, IPos *b, double *dist_out) {
    StructureConfig sc;
    if (!getStructureConfig(Monument, mc, &sc)) {
        fprintf(stderr, "Monument unsupported for mc=%d\n", mc);
        exit(2);
    }

    int chunk_radius = (radius + 15) / 16;
    int reg_min = (int)floor((double)(-chunk_radius - sc.regionSize) / sc.regionSize);
    int reg_max = (int)ceil((double)(chunk_radius + sc.regionSize) / sc.regionSize);
    int max_positions = (reg_max - reg_min + 1) * (reg_max - reg_min + 1);
    MonumentAttempt *pos = (MonumentAttempt *)malloc((size_t)max_positions * sizeof(MonumentAttempt));
    if (!pos) { perror("malloc positions"); exit(1); }
    int n = 0;

    // First collect raw monument attempts inside the search square. This is cheap.
    // Biome viability is much more expensive, so we only call it for close pairs.
    int64_t r2 = (int64_t) radius * radius;
    for (int rz = reg_min; rz <= reg_max; rz++) {
        for (int rx = reg_min; rx <= reg_max; rx++) {
            Pos p;
            if (!getStructurePos(Monument, mc, seed, rx, rz, &p)) continue;
            if (p.x < -radius || p.x > radius || p.z < -radius || p.z > radius) continue;
            if (circle && (int64_t)p.x * p.x + (int64_t)p.z * p.z > r2) continue;
            pos[n++] = (MonumentAttempt){rx, rz, p.x, p.z};
        }
    }

    if (n < 2) {
        free(pos);
        return false;
    }

    Generator g;
    setupGenerator(&g, mc, 0);
    applySeed(&g, DIM_OVERWORLD, seed);

    int maxd2 = maxdist * maxdist;
    for (int i = 0; i < n; i++) {
        for (int j = i + 1; j < n; j++) {
            // With 32x32 chunk monument regions, a <=256 block pair can only happen
            // in the same or neighboring region cells. This avoids most pair checks.
            if (abs(pos[i].rx - pos[j].rx) > 1 || abs(pos[i].rz - pos[j].rz) > 1) continue;
            int dx = pos[i].x - pos[j].x;
            int dz = pos[i].z - pos[j].z;
            if (dx < -maxdist || dx > maxdist || dz < -maxdist || dz > maxdist) continue;
            int d2 = dx * dx + dz * dz;
            if (d2 > maxd2) continue;
            if (!isViableStructurePos(Monument, &g, pos[i].x, pos[i].z, 0)) continue;
            if (!isViableStructurePos(Monument, &g, pos[j].x, pos[j].z, 0)) continue;
            *a = (IPos){pos[i].x, pos[i].z};
            *b = (IPos){pos[j].x, pos[j].z};
            *dist_out = sqrt((double)d2);
            free(pos);
            return true;
        }
    }
    free(pos);
    return false;
}

int main(int argc, char **argv) {
    const char *in_path = NULL;
    const char *out_path = NULL;
    const char *mc_name = "newest";
    int radius = 10000;
    int maxdist = 256;
    bool circle = false;
    long limit = 0;

    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--in") && i + 1 < argc) in_path = argv[++i];
        else if (!strcmp(argv[i], "--out") && i + 1 < argc) out_path = argv[++i];
        else if (!strcmp(argv[i], "--radius-blocks") && i + 1 < argc) radius = (int)parse_long_arg(argv[++i], "radius-blocks");
        else if (!strcmp(argv[i], "--max-distance") && i + 1 < argc) maxdist = (int)parse_long_arg(argv[++i], "max-distance");
        else if (!strcmp(argv[i], "--mc") && i + 1 < argc) mc_name = argv[++i];
        else if (!strcmp(argv[i], "--circle")) circle = true;
        else if (!strcmp(argv[i], "--limit") && i + 1 < argc) limit = parse_long_arg(argv[++i], "limit");
        else { usage(argv[0]); return 2; }
    }
    if (!in_path || !out_path) { usage(argv[0]); return 2; }

    int mc = parse_mc(mc_name);
    FILE *in = fopen(in_path, "r");
    if (!in) { perror(in_path); return 1; }
    FILE *out = fopen(out_path, "w");
    if (!out) { perror(out_path); fclose(in); return 1; }

    char line[4096];
    if (!fgets(line, sizeof(line), in)) {
        fprintf(stderr, "empty input\n");
        fclose(in); fclose(out);
        return 1;
    }
    fprintf(out, "seed,monument1_x,monument1_z,monument2_x,monument2_z,distance_blocks,mc_approx,radius_blocks,max_distance_blocks\n");

    long processed = 0;
    long hits = 0;
    while (fgets(line, sizeof(line), in)) {
        if (limit > 0 && processed >= limit) break;
        if (!isdigit((unsigned char)line[0]) && line[0] != '-') continue;
        int64_t s = parse_seed_from_csv_line(line);
        IPos a = {0,0}, b = {0,0};
        double dist = 0.0;
        if (find_double_monument((uint64_t)s, mc, radius, maxdist, circle, &a, &b, &dist)) {
            fprintf(out, "%" PRId64 ",%d,%d,%d,%d,%.3f,%s,%d,%d\n", s, a.x, a.z, b.x, b.z, dist, mc_name, radius, maxdist);
            hits++;
        }
        processed++;
        if (processed % 1000 == 0) {
            fprintf(stderr, "processed=%ld hits=%ld\n", processed, hits);
            fflush(stderr);
        }
    }

    fclose(in);
    fclose(out);
    fprintf(stderr, "done: processed=%ld hits=%ld output=%s\n", processed, hits, out_path);
    return 0;
}
