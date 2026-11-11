#!/usr/bin/env bash
# 示例配置：E 机。复制为 env_evior.sh 后填入你自己的地址。
# 真实配置含主机/私钥路径，已被 .gitignore 排除，不要提交到公开仓库。
export RG_HOST="${RG_HOST:-YOUR_USER@YOUR_HOST}"
export RG_ALT_HOST="YOUR_USER@YOUR_ALT_HOST"
export RG_KEY="C:/path/to/your/ssh/key"
export RG_BASE_WIN='D:\yourdir'
export RG_BASE_UNIX='D:/yourdir'
export RG_BATCH='D:\Program Files\COMSOL\COMSOL64\Multiphysics\bin\win64\comsolbatch.exe'
export RG_COMPILE='D:\Program Files\COMSOL\COMSOL64\Multiphysics\bin\win64\comsolcompile.exe'
export RG_CORES=24
