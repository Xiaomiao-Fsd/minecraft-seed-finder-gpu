# Minecraft Seed Finder GPU

一个可暂停、可恢复、支持多 NVIDIA GPU 的 Minecraft Java 种子粗筛工具。

当前重点加速第一层：**史莱姆区块密集度粗筛**。它适合先在大量 seed 中快速筛出候选，再交给 cubiomes / 自定义 checker 做群系、海底神殿、下界堡垒等更精细的验证。


## 版本说明

### v0.1.1

- 修复 Java 史莱姆区块公式的 32-bit `int` 溢出模拟。现在 CPU/CUDA 后端与原版 Java / Chunkbase 行为一致。
- 如果你使用过 v0.1.0 生成候选，请重新运行史莱姆粗筛。

## 功能

- CUDA GPU 后端：可调用 NVIDIA GPU 跑史莱姆粗筛。
- CPU 后端：没有 CUDA 时也可以跑，只是速度较低。
- 一键启动：输入要搜索的种子数量即可运行。
- 多 GPU：单机 4×V100 场景下，一张 GPU 一个 worker。
- 暂停 / 恢复：按 chunk 写 checkpoint，已完成 chunk 不会重跑。
- 进度记录：`state.json` 记录当前 seed 估计值、完成数量、worker/GPU 状态。
- 自动合并：全部完成后合并为 `candidates_merged.csv`。

## 适用环境

推荐：Ubuntu / Linux + NVIDIA GPU。

基础依赖：

```bash
sudo apt update
sudo apt install -y python3 gcc make
```

CUDA GPU 运行需要：

```bash
nvidia-smi
nvcc --version
```

如果没有 `nvidia-smi` 或 `nvcc`，CUDA 后端不可用。普通虚拟机里的 `VMware SVGA` / `VirtualBox Graphics` 不能跑 CUDA；需要真实 NVIDIA GPU、WSL2 CUDA，或者 GPU passthrough。

## 快速开始：4×V100

下载 release 包后：

```bash
tar -xzf minecraft-seed-finder-gpu-v0.1.0.tar.gz
cd minecraft-seed-finder-gpu-v0.1.0
```

在 4 张 V100 上跑 1 亿个 seed：

```bash
MC_SEED_BACKEND=cuda MC_SEED_GPUS=0,1,2,3 ./run_seed_cluster.sh 100000000
```

跑 10 亿个 seed：

```bash
MC_SEED_BACKEND=cuda MC_SEED_GPUS=0,1,2,3 ./run_seed_cluster.sh 1b
```

不带数量时会交互询问：

```bash
./run_seed_cluster.sh
```

数量支持后缀：

- `100m` = 100,000,000
- `1b` / `1g` = 1,000,000,000
- `1t` = 1,000,000,000,000

## 管理运行任务

每次运行会创建一个目录：

```text
runs/cluster_YYYYMMDD_HHMMSS/
  state.json
  config.json
  control/PAUSE
  chunks/chunk_000000.csv
  logs/chunk_000000.log
  candidates_merged.csv
```

查看状态：

```bash
./run_seed_cluster.sh status runs/cluster_YYYYMMDD_HHMMSS
```

请求暂停：

```bash
./run_seed_cluster.sh pause runs/cluster_YYYYMMDD_HHMMSS
```

恢复运行：

```bash
./run_seed_cluster.sh resume runs/cluster_YYYYMMDD_HHMMSS
```

手动合并已完成 chunk：

```bash
./run_seed_cluster.sh merge runs/cluster_YYYYMMDD_HHMMSS
```

注意：暂停是 **chunk 边界暂停**。当前 chunk 会先跑完，再退出。默认每 1000 万 seeds 一个 chunk。

如果想让暂停响应更快，可以调小 chunk：

```bash
MC_SEED_CHUNK_SIZE=1000000 MC_SEED_BACKEND=cuda MC_SEED_GPUS=0,1,2,3 ./run_seed_cluster.sh 1b
```

## 常用环境变量

```bash
MC_SEED_BACKEND=auto|cuda|cpu       # 默认 auto
MC_SEED_GPUS=auto|0,1,2,3           # 默认 auto
MC_SEED_CHUNK_SIZE=10000000         # 默认 1000 万 seeds 一个 checkpoint chunk
MC_SEED_START=0                     # 默认从 seed 0 开始
MC_SEED_RUN_NAME=my_run             # 可选，指定 runs/ 下运行目录名
MC_SEED_CONFIG=config.example.json  # 可选，指定配置文件
```

## 后台长期运行

推荐用 `tmux`：

```bash
tmux new -s mcseed
MC_SEED_BACKEND=cuda MC_SEED_GPUS=0,1,2,3 ./run_seed_cluster.sh 1b
```

断开后重新进入：

```bash
tmux attach -t mcseed
```

也可以用 `nohup`：

```bash
nohup env MC_SEED_BACKEND=cuda MC_SEED_GPUS=0,1,2,3 ./run_seed_cluster.sh 1b > mcseed.log 2>&1 &
```

## 单机多 GPU 与多节点

单机 4×V100：

```bash
MC_SEED_BACKEND=cuda MC_SEED_GPUS=0,1,2,3 ./run_seed_cluster.sh 1b
```

多节点集群可以手动切分 seed 区间。例如两台节点各跑 10 亿：

节点 A：

```bash
MC_SEED_START=0 MC_SEED_BACKEND=cuda MC_SEED_GPUS=0,1,2,3 ./run_seed_cluster.sh 1b
```

节点 B：

```bash
MC_SEED_START=1000000000 MC_SEED_BACKEND=cuda MC_SEED_GPUS=0,1,2,3 ./run_seed_cluster.sh 1b
```

如果使用 Slurm / PBS，可以把这两组变量放进作业脚本。

## 直接使用底层命令

编译 CUDA 版：

```bash
python3 seed_finder.py build --backend cuda
```

直接跑 CUDA 粗筛：

```bash
python3 seed_finder.py slime-prefilter --backend cuda --start 0 --count 100000000
```

CPU 回落：

```bash
python3 seed_finder.py slime-prefilter --backend cpu --start 0 --count 1000000
```

## 输出 CSV

粗筛输出列：

```text
seed,best_slime_chunks,best_center_chunk_x,best_center_chunk_z,center_samples,circle_radius_chunks,search_radius_chunks
```

完成后总表：

```text
runs/<run>/candidates_merged.csv
```

## 参数说明

默认配置在 `config.example.json`：

```json
"threshold_chunks": 38,
"final_threshold_chunks": 20,
"circle_radius_blocks": 128,
"search_radius_blocks": 10000,
"center_samples": 64
```

含义：

- `threshold_chunks`: 粗筛阈值。越高越快压缩候选，但可能漏掉只刚好满足最终条件的 seed。
- `final_threshold_chunks`: 最终确认阈值。
- `circle_radius_blocks`: 史莱姆圆半径，默认 128 格。
- `search_radius_blocks`: 圆心搜索半径，默认原点 10000 格内。
- `center_samples`: 每个 seed 采样多少个候选圆心。

## 当前限制

- CUDA 版只加速史莱姆粗筛。
- 群系 / 海底神殿 / 下界堡垒等精筛仍需要 cubiomes 或自定义 checker。
- 暂停粒度是 chunk 级，不是 GPU kernel 内即时暂停。
- 当前 Minecraft 26.2 / 26.2-pre1 的完整世界生成规则需要外部工具进一步确认。

## 打包 release

仓库内置打包脚本：

```bash
scripts/package_release.sh v0.1.0
```

它会生成：

```text
dist/minecraft-seed-finder-gpu-v0.1.0.tar.gz
dist/minecraft-seed-finder-gpu-v0.1.0.zip
```
