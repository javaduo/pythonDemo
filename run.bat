    @echo off
    REM 切换到当前批处理文件所在的目录
    cd /d %~dp0
    
    REM 执行Python脚本
    python app.py
    
    REM 保持窗口打开，以便查看输出结果，按任意键关闭
    pause