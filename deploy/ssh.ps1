# 快速 SSH 登录 EC2 服务器
$PEM = "C:\Users\xiong\Downloads\ios ranking system.pem"
ssh -o StrictHostKeyChecking=no -o ServerAliveInterval=30 -i $PEM ubuntu@13.215.194.223 -t "cd /home/ubuntu/IOSAgent 2>/dev/null; exec bash"
