import time

start = time.perf_counter()
print("test")
end = time.perf_counter()
print(f"print 耗时: {(end - start) * 1000:.3f} ms")
