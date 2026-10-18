# CUDA 11.8 — Last Toolkit Supporting Tesla K80

## Summary

| Item | Value |
|------|-------|
| GPU | NVIDIA Tesla K80 |
| Architecture | Kepler (GK210) |
| Compute Capability | 3.7 (`sm_37`) |
| Last CUDA Toolkit | **11.8.0** |
| Last Driver Branch | R470 |
| Dropped in | CUDA 12.0 |

NVIDIA’s official CUDA Toolkit / Driver / Architecture matrix lists Kepler compute capability 3.5 and 3.7 (includes Tesla K80) as having last toolkit support in **CUDA 11.x**. CUDA 11.8.0 is the final release in that series.

## Official Download

**Linux runfile (recommended for most setups):**

```
https://developer.download.nvidia.com/compute/cuda/11.8.0/local_installers/cuda_11.8.0_520.61.05_linux.run
```

**Archive page:**
https://developer.nvidia.com/cuda-11-8-0-download-archive

**Documentation:**
https://docs.nvidia.com/cuda/archive/11.8.0/

## Quick Install (Linux)

```bash
# Download
wget https://developer.download.nvidia.com/compute/cuda/11.8.0/local_installers/cuda_11.8.0_520.61.05_linux.run

# Make executable and install toolkit only (no driver if you already have a compatible one)
chmod +x cuda_11.8.0_520.61.05_linux.run
sudo sh cuda_11.8.0_520.61.05_linux.run --toolkit --silent --override

# Or interactive
sudo sh cuda_11.8.0_520.61.05_linux.run
```

After installation, add to your environment (typical paths):

```bash
export PATH=/usr/local/cuda-11.8/bin:$PATH
export LD_LIBRARY_PATH=/usr/local/cuda-11.8/lib64:$LD_LIBRARY_PATH
```

## Driver Notes

- The R470 driver branch is the last that officially supports Kepler (K80).
- For production Tesla use, prefer the appropriate data-center driver from NVIDIA that matches your OS and the R470 / CUDA 11.x line.
- CUDA 11.8 toolkit can often run on a minimum driver of ~450.80.02 (Linux) via compatibility, but R470 is the recommended / last supported branch for K80.

## Open Source Components

CUDA Samples for 11.8 are available separately:

```
git clone --branch v11.8 https://github.com/NVIDIA/cuda-samples.git
```

## License

The CUDA Toolkit is proprietary software. By downloading and using it you agree to the NVIDIA CUDA EULA. This repository does not redistribute the toolkit binaries.
