# Tesla K80 Drivers and Interconnector

## Official Baseline (R470)

NVIDIA ended regular support for Kepler (including Tesla K80) with the R470 driver branch.

- Last driver support for compute capability 3.5 / 3.7: **R470**
- Last CUDA Toolkit that can target `sm_37`: **11.8**
- R470 reached end of life around mid-2024

### Known Data Center References

- Release notes example: Version 470.129.06 (Linux) / 473.47 (Windows)
- Official matrix confirms Tesla K80 is listed under Kepler support in the R470 family
- Download from NVIDIA:
  - https://www.nvidia.com/Download/index.aspx (select Tesla / Data Center, K80 or Kepler, R470 branch)
  - Data center driver documentation: https://docs.nvidia.com/datacenter/tesla/

Do not redistribute proprietary driver binaries in this repository. Install the official R470 package for your OS, then build the custom interconnector on top.

## Custom Interconnector (Goal)

The interconnector is the remastering layer:

1. Talks to the K80 through the last supported official driver / CUDA 11.8 runtime.
2. Exposes a modern interface (model formats, batching, dual-die placement, API compatible with newer cluster nodes).
3. Lets the K80 act as a dedicated backend while other GPUs run different workloads.

### Planned structure

```
drivers/
  interconnector/          # custom translation / runtime layer
  k80_baseline.md          # verified R470 + CUDA 11.8 notes
  hybrid_cluster.md        # how K80 nodes sit alongside newer cards
```

Implementation starts here. The official R470 driver remains the hardware foundation; everything above it is the remaster.
