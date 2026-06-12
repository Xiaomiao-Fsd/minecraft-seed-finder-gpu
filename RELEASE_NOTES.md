# v0.1.0

首个公开 release。

## 包含内容

- CUDA / CPU 史莱姆区块密集度粗筛器。
- 一键多 GPU runner：适合 4×V100 单节点。
- 暂停、恢复、状态查询、chunk checkpoint。
- Release 打包脚本。
- 中文 README 使用指引。

## 快速运行

```bash
tar -xzf minecraft-seed-finder-gpu-v0.1.0.tar.gz
cd minecraft-seed-finder-gpu-v0.1.0
MC_SEED_BACKEND=cuda MC_SEED_GPUS=0,1,2,3 ./run_seed_cluster.sh 100000000
```
