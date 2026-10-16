# Worker Lambda image: the full rendering stack (rembg + onnxruntime CPU), with the background-removal model baked in.
# Built from the repo root (see .dockerignore): docker build -f docker/worker.Dockerfile .

# ---- Build stage: install dependencies and download the model ----
FROM public.ecr.aws/lambda/python:3.13 AS build

# Dependencies come from pyproject.toml alone, so this layer (and the 2.4GB it installs) is rebuilt only when they change, never for a code change.
# pip still needs a package to build, so a one-line stand-in takes the real code's place here, and is removed straight after
COPY pyproject.toml /build/
RUN mkdir -p /build/src/taleboard && touch /build/src/taleboard/__init__.py

# The [worker] extra pulls in Together and rembg's CPU build (no GPU on Lambda), on top of the shared core
RUN pip install --no-cache-dir --target /build/package "/build[worker]" && rm -rf /build/package/taleboard /build/package/taleboard-*.dist-info

# rembg normally downloads its model on first use -- fetch it now, so a cold start never touches the network.
# Must match background_removal.py's new_session("isnet-anime"); never swap for BRIA RMBG 2.0 (it ran out of memory on CPU)
ENV U2NET_HOME=/build/models
RUN PYTHONPATH=/build/package python -c "from rembg import new_session; new_session('isnet-anime', providers=['CPUExecutionProvider'])"

# Pre-compiles the bytecode, so the read-only Lambda filesystem never has to (and cold starts skip it)
RUN python -m compileall -q /build/package

# The code itself, only now -- everything above is reused from the cache when only the code has changed
COPY src/taleboard/ /build/app/taleboard/
RUN python -m compileall -q /build/app

# ---- Final stage: only the runtime artifacts ----
FROM public.ecr.aws/lambda/python:3.13

COPY --from=build /build/package ${LAMBDA_TASK_ROOT}
COPY --from=build /build/models /opt/models

ENV U2NET_HOME=/opt/models

# pymatting (a rembg dependency) compiles its numba functions on import -- 40-60 s on every cold start if left alone.
# Compile them once here, in the final stage, so the cache matches the /var/task paths the code runs from
RUN NUMBA_CACHE_DIR=/opt/numba-cache python -c "import rembg"

# Lambda runs the handler as a non-root user, but the model and numba cache were written by root with owner-only permissions
RUN chmod -R a+rX /opt/models /opt/numba-cache

# Numba refuses to run with a read-only cache dir, and /opt is read-only on Lambda -- so the entrypoint copies the cache into /tmp first
COPY --chmod=755 docker/worker-entrypoint.sh /opt/worker-entrypoint.sh
ENV NUMBA_CACHE_DIR=/tmp/numba-cache

# The code goes in last, so a code-only change rebuilds (and pushes) just this small layer
COPY --from=build /build/app ${LAMBDA_TASK_ROOT}

ENTRYPOINT ["/opt/worker-entrypoint.sh"]
CMD ["taleboard.jobs.worker.handler"]