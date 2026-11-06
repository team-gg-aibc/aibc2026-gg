"""팀 GG 엔진: 서울특별시 조례 6종 질의응답. 사용법은 engine/README.md."""
import os

# 행렬 계산(BLAS)은 한 스레드로 한다. 여러 문항을 동시에 돌릴 때(채점 서버 · 점수 틀) BLAS 스레드와 하위 프로세스 띄우기가
# 겹치면 옛 OpenBLAS(conda numpy 1.26 판)가 멈춘다(11-06 재현: 3번 모두 60초 넘게 멈춤, 한 스레드면 1.7초에 끝남).
# 조각 528개짜리 계산이라 한 스레드여도 느려지지 않는다. numpy를 부르기 전에 정해야 해서 여기 둔다.
for _name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_name, "1")
