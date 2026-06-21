import socket

def test_redis():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1.0)
    try:
        s.connect(('127.0.0.1', 6379))
        print("Redis is RUNNING on port 6379")
        s.close()
        return True
    except Exception as e:
        print(f"Redis is NOT running: {e}")
        return False

if __name__ == '__main__':
    test_redis()
