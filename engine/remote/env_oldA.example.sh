#!/usr/bin/env bash
# 示例配置：A 机（远程公共机）。复制为 env_oldA.sh 后填入你自己的地址。
# 真实配置含主机/私钥路径，已被 .gitignore 排除，不要提交到公开仓库。
export RG_HOST="YOUR_USER@YOUR_HOST"                 # 例: admin@10.0.0.1
export RG_KEY="C:/path/to/your/ssh/key"              # SSH 私钥
export RG_BASE_WIN='D:\model\yourdir'                # 远程可写工作目录（Windows 形式）
export RG_BASE_UNIX='D:/model/yourdir'               # 同上（scp 形式）
export RG_BATCH='D:\COMSOL64\Multiphysics\bin\win64\comsolbatch.exe'
export RG_COMPILE='D:\COMSOL64\Multiphysics\bin\win64\comsolcompile.exe'
