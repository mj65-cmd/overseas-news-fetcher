# FOSS Weekly #26.36: Debian CERN Win, Faster Firefox, Free Bash Course, Grub Customization and More Linux Stuff
领域：免费工具/开源软件
原文链接：https://feed.itsfoss.com/link/24361/17439066/foss-weekly-26-36

# 为什么你在 Linux 上收不到 iPhone 信息？免费白嫖 Tether 一键搞定  

你是不是在用 Linux 桌面，却发现 iPhone 的 iMessage、短信、验证码根本收不到？  
别急，很多人都卡在这儿——因为 Linux 原生根本没有 Apple 的 Continuity 功能。  
其实只要装一个开源的 **Tether**，就能把 iMessage、SMS、OTP 代码通过蓝牙同步到 Linux，完全免费。

## 为什么你做不成？卡在哪儿  
- **系统不兼容**：Linux 没有官方的 Continuity 实现，导致 iPhone 与电脑之间的消息无法互通。  
- **缺少合适的工具**：大多数人只会在 iPhone 上看信息，或者把手机当作唯一的验证码接收端，根本不知道有开源替代方案。  
- **误以为只能买付费软件**：看到市面上各种“跨平台短信同步”往往是收费的，导致放弃尝试。  

## 具体怎么干  
1. **找到 Tether 项目**  
   - 在原文中提到 “developer has managed to bring a comparable experience with **Tether**, an open source app”。  
   - 直接在搜索引擎或 GitHub 上搜索 “Tether iPhone Linux” 即可找到项目主页。  

2. **下载并安装**  
   - 原文未提及具体的安装步骤，建议参考项目的 README 或官方文档进行安装（通常是 `git clone` + 编译，或提供的 `.deb` 包直接安装）。  

3. **配对蓝牙**  
   - Tether 通过蓝牙把 iPhone 与 Linux 连接。  
   - 按照项目文档打开蓝牙、在 iPhone 上允许配对，然后在 Linux 上启动 Tether 即可。  

4. **开始接收信息**  
   - 配对成功后，iMessage、SMS、以及 OTP 代码会自动转发到 Linux，和普通聊天软件一样显示。  

> **注意**：以上步骤均基于原文提到的功能，具体的命令或 UI 操作请参考 Tether 项目的官方说明，原文未提供细节。

## 避坑指南  
- **别忘了蓝牙权限**：Linux 需要对蓝牙设备有读写权限，未授权会导致配对失败。  
- **检查 iPhone 的蓝牙可见性**：配对前确保 iPhone 处于可发现状态，否则 Linux 找不到设备。  
- **不要混用多个同步工具**：同时运行类似的短信同步软件可能会产生冲突，导致信息丢失。  

## 关键数据  
- 原文未提及具体的效果数据、时间或成本。  

## 普通人能抄什么  
1. **搜索并打开 Tether 项目页面**（GitHub 或官方站点），下载最新的发布版本。  
2. **按照项目文档完成安装**（如使用 `dpkg -i` 安装 `.deb` 包或编译源码）。  
3. **在 Linux 与 iPhone 之间配对蓝牙**，启动 Tether，即可在电脑上收到 iMessage、短信和 OTP。  

把 iPhone 的信息搬到 Linux 只需要这三步，马上试试，让你的工作流彻底摆脱手机的束缚吧！
