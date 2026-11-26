import os
import tempfile

# 须在导入 app 之前落定数据库路径（config 在导入时读取）
os.environ["SHIPGATE_DB"] = os.path.join(tempfile.mkdtemp(prefix="shipgate-test-"), "session.db")
