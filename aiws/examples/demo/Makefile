test:
	python3 -m unittest -v

# CPU-heavy, good for sending to another machine: `ai job run --tags build 'make -C ~/src/demo bench'`
bench:
	python3 -c "import random,time,mergesort as m; xs=[random.random() for _ in range(300000)]; t=time.time(); m.sort(xs); print(f'sorted 300k in {time.time()-t:.2f}s on', __import__('socket').gethostname())"
