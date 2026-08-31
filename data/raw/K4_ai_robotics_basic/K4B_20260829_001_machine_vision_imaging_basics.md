# 机器视觉与成像基础：2D/3D 视觉系统、相机标定与点云

- 来源 URL：[OpenCV Camera Calibration and 3D Reconstruction](https://docs.opencv.org/4.10.0/d9/d0c/group__calib3d.html)；[2D or 3D for Your Machine Vision Application — STEMMER IMAGING](https://www.stemmer-imagingusa.com/blog/2d-or-3d-for-your-machine-vision-application)
- 作者/机构：OpenCV 官方文档 / STEMMER IMAGING；本文由 XH-agent 基于公开资料二次整理
- 发布日期：OpenCV 4.10（2024）/ STEMMER IMAGING；本文整理日期 2026-08-29
- 来源权威等级：B
- 内容性质：公开文档的中文工程化二次整理；公式为通用数学表达，非某一厂商专有
- 领域标签：K4B_机器视觉成像
- 摘要：解释工业机器人 AI 视觉最底层的成像常识：针孔相机模型、内参/外参与畸变、2D 与 3D 视觉的边界、点云及其处理。适用于理解后续「手眼标定」「3D 引导抓取」等实操文档的前置概念。

---

## 正文

### 1. 相机怎么把三维世界变成二维图像

工业视觉几乎都建立在**针孔相机模型（pinhole camera model）**之上：三维空间点经过透视投影落到图像平面。核心投影方程：

```text
s · p = A · [R|t] · Pw
```

- `Pw`：三维世界坐标点；
- `p`：投影到像素平面的二维点；
- `A`：相机内参矩阵；
- `[R|t]`：外参（旋转 + 平移）；
- `s`：尺度因子。

理解这个方程，是理解「AI 视觉给出像素结果，机器人怎么换算成空间动作」的第一步。

### 2. 内参、外参与畸变

**内参（intrinsic，相机固有）** 是一个 3×3 矩阵：

```text
A = [ fx   0   cx ]
    [ 0    fy  cy ]
    [ 0    0   1  ]
```

- `fx / fy`：以像素为单位的焦距；
- `cx / cy`：主点（光心，通常在图像中心）。

内参只跟相机本身有关，焦距不变就能复用；图像缩放时内参要按比例缩放。

**外参（extrinsic）** 描述相机在世界坐标系中的位姿，是旋转 `R` 和平移 `t` 组成的刚体变换，把世界坐标变换到相机坐标。

**畸变（distortion）** 是真实镜头偏离理想针孔模型的部分：

- **径向畸变**（直线变弯）：`x_dist = x(1 + k₁r² + k₂r⁴ + k₃r⁶)`；
- **切向畸变**（镜头与成像面不平行）：由 `p₁、p₂` 描述。

五个基本畸变系数是 `(k₁, k₂, p₁, p₂, k₃)`。标定的本质就是解出这些参数，把「带畸变的像素」还原成「理想投影」。

### 3. 相机标定流程

以 OpenCV 的标准流程为例：

1. 用棋盘格或圆点板采集**至少约 10 个不同姿态**的图像；
2. 检测角点（`findChessboardCorners`）并亚像素细化（`cornerSubPix`）；
3. 用三维物点 + 二维像点调用 `calibrateCamera` 解出内参、畸变、外参；
4. 用 `undistort` 或 `remap` 做去畸变；
5. 用重投影误差验证——RMS 误差小于约 1 像素视为标定良好。

### 4. 2D 与 3D 视觉的边界

**2D 视觉**只得到 X、Y 二维灰度/彩色图像，靠对比度、边缘、形状、颜色判读，适合条码读取、标签校验、有无检测、平面零件定位。局限是**测不了高度/深度**、对光照和对比度敏感。

**3D 视觉**额外得到 Z（深度），输出**点云（point cloud）**或**深度图（depth map）**，适合散乱/堆叠/不规则物体的抓取、碰撞规避、体积测量。主要 3D 成像技术：

| 技术 | 原理 | 特点 |
|------|------|------|
| 双目立体（stereo） | 两相机视差算深度 | 近距精度高、成本低，弱光差 |
| 结构光（structured light） | 投射已知光斑测形变 | 计算简单、精度好，怕强环境光 |
| 飞行时间（ToF） | 测光飞行时间 | 快、距离远，分辨率较低、成本高 |
| 激光三角（laser triangulation） | 激光线三角测距 | 精确、快、便宜，精度随距离下降 |

二者**互补而非替代**：2D 查表面划痕/污染，3D 查凹凸/深度缺陷，产线上常组合使用。

### 5. 点云及其处理

点云是「物体位置 + 形状」的数字化模型。原始点云通常带噪声，基本处理链：

1. **滤波**（如 SOR 统计滤波）去噪，保留几何细节；
2. **平滑**（如 MLS）生成致密表面，但可能磨平细节、速度慢；
3. **配准**——把两片点云对齐，常用：
   - **ICP（迭代最近点）**：迭代最小化均方误差，适合初始位置接近的两片云，对缺失/错配敏感；
   - **特征匹配 + RANSAC**（如 FPFH 描述子 + 采样一致预配准）：在初始位姿未知时更鲁棒。

3D 的分辨率主要由**点云密度**决定，而不是传感器像素数；强光、反光、遮挡会导致点云缺失（dropout）。

## 适用场景

AI 视觉引导抓取、3D 定位、缺陷检测前的成像方案选型与标定准备；是 K4P 实操文档（ABB/Cognex/HALCON/Isaac）的概念底座。

## 参考资料

1. [OpenCV: Camera Calibration and 3D Reconstruction](https://docs.opencv.org/4.10.0/d9/d0c/group__calib3d.html)
2. [2D or 3D for Your Machine Vision Application — STEMMER IMAGING](https://www.stemmer-imagingusa.com/blog/2d-or-3d-for-your-machine-vision-application)

<!-- self_check: K4B_20260829_001 ✓ ①②③④⑤⑥⑦ -->
