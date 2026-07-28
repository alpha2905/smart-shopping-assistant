import sys
import asyncio

# Bắt buộc đặt thiết lập này lên dòng đầu tiên trước mọi import liên quan đến async/playwright trên Windows
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import uvicorn

if __name__ == "__main__":
    # Chạy uvicorn trực tiếp thông qua script python
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)