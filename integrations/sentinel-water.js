//VERSION=3
// Sentinel-2 L2A surface-water heuristic, NOT validated event-flood detection.
// Valid land is opaque black; detected water opaque blue; unknown is transparent.
// Backend rejects rasters containing ANY unknown pixel for the requested area.
function setup() {
  return {
    input: [{bands: ["B03", "B08", "SCL", "dataMask"]}],
    output: {bands: 4, sampleType: "AUTO"}
  };
}
function evaluatePixel(sample) {
  if (!sample.dataMask || ![4, 5, 6, 7].includes(sample.SCL)) return [0, 0, 0, 0];
  const denominator = sample.B03 + sample.B08;
  if (denominator <= 0) return [0, 0, 0, 0];
  const ndwi = (sample.B03 - sample.B08) / denominator;
  return ndwi > 0.3 ? [0, 0, 1, 1] : [0, 0, 0, 1];
}
