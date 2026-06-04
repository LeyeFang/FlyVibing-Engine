import time


tik_tok_time = time.perf_counter()
def tic():
    global tik_tok_time
    tik_tok_time = time.perf_counter()


def toc():
    global tik_tok_time
    return time.perf_counter() - tik_tok_time


def sleep(time_in_s: float):
    start_time = time.perf_counter()
    # time.sleep(time_in_s)
    while (time.perf_counter()-start_time) < time_in_s:
        pass


_start_time = time.perf_counter()


def GetRunTime():
    return time.perf_counter() - _start_time


def ResetStartTime():
    global _start_time
    _start_time = time.perf_counter()
