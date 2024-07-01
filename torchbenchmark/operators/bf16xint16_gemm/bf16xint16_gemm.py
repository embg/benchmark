"""
Compute a bf16 (activation) x int16 (weight) gemm.
A stepping stone to a fast int4_gemm (another TritonBench kernel)
bf16xbf16 baseline implementation taken from the triton tutorial
  https://triton-lang.org/main/getting-started/tutorials/03-matrix-multiplication.html
and the bf16xint16 implementation is a modified version of the same
  tutorial kernel.
"""

import argparse
import os
import statistics

from typing import Any

import torch
import triton
import triton.language as tl

from torchbenchmark.util.triton_op import (
    BenchmarkOperator,
    BenchmarkOperatorMetrics,
    register_benchmark,
    register_metric,
)

from .kernel import (
    bf16xbf16_matmul,
    bf16xbf16_matmul_kernel,
    bf16xint16_matmul,
    bf16xint16_matmul_kernel,
)


class Operator(BenchmarkOperator):
    DEFAULT_METRICS = ["tflops", "gbps", "latency"]

    def __init__(self, mode, device, extra_args):
        super().__init__(mode=mode, device=device, extra_args=extra_args)
        # `Group size` and `inner K tiles` are defaults from gpt-fast.
        self.group_size = 32
        self.inner_k_tiles = 8

    def get_input_iter(self):
        def args(B, L, Dout, Din):
            x = torch.randn(B, L, Din, device=self.device, dtype=torch.bfloat16)
            w = torch.randn(
                Din,
                Dout,
                device=self.device,
                dtype=torch.bfloat16,
            )
            return (x, w)

        # LLama-2 shapes w/ 8-way tensor parallelism.
        name_to_shapes_70b = {
            "attn.wqkv": (8192, 1280),
            "attn.w0": (1024, 8192),
            "ffn.w13": (8192, 7168),
            "ffn.w2": (3584, 8192),
        }
        for seq_len in (1, 4096):
            for bsz in (1, 4, 16, 64):
                for name, (k, n) in name_to_shapes_70b.items():
                    yield args(bsz, seq_len, n, k)

    def get_x_val(self, example_inputs) -> float:
        x, w = example_inputs
        B, m, k = x.size()
        _, n = w.size()
        return (B, m, n, k)

    @register_benchmark(baseline=True)
    def bf16xbf16(self, x, w):
        x = x.reshape(-1, x.size(-1))
        w_bf16 = w.to(torch.bfloat16)
        return lambda: bf16xbf16_matmul(x, w_bf16)

    @register_benchmark()
    def bf16xint16(self, x, w):
        x = x.reshape(-1, x.size(-1))
        return lambda: bf16xint16_matmul(x, w)

    @register_benchmark()
    def bf16xint16_casted(self, x, w):
        x = x.reshape(-1, x.size(-1))
        return lambda: bf16xbf16_matmul(x, w.to(torch.bfloat16))

    @register_metric()
    def best_config(self, fn, inputs, metrics):
        if "bf16xbf16" in str(fn):
            return str(bf16xbf16_matmul_kernel.best_config)
        if "bf16xint16" in str(fn) and "casted" not in str(fn):
            return str(bf16xint16_matmul_kernel.best_config)
        return ""

    @register_metric()
    def gbps(self, fn, example_inputs: Any, metrics: BenchmarkOperatorMetrics) -> float:
        def nbytes(t):
            return t.numel() * t.element_size()

        x, w = example_inputs
        c = fn()

        gb = (sum(nbytes(t) for t in (x, c)) + nbytes(w) // 8) / 1e9
        return gb / metrics.latency * 1e3

    @register_metric()
    def tflops(
        self, fn_name: str, example_inputs: Any, metrics: BenchmarkOperatorMetrics
    ) -> float:
        a, b = example_inputs
        B, m, k = a.size()
        m = B * m
        _, n = b.size()
        flops = 2 * m * n * k
        return flops / metrics.latency / 1e12 * 1e3

    def plot(self):
        @triton.testing.perf_report(
            triton.testing.Benchmark(
                x_names=[
                    "B",
                    "m",
                    "n",
                    "k",
                ],  # argument names to use as an x-axis for the plot
                x_vals=self.output.x_vals,  # different possible values for `x_name`
                line_arg="provider",  # argument name whose value corresponds to a different line in the plot
                line_vals=[
                    "torch",
                    "triton",
                ],  # possible values for `line_arg``
                line_names=[
                    "torch",
                    "triton",
                ],  # label name for the lines
                styles=[("blue", "-"), ("green", "-")],
                ylabel="tflops",  # label name for the y-axis
                plot_name="int4-gemm-performance",  # name for the plot. Used also as a file name for saving the plot.
                args={},  # values for function arguments not in `x_names` and `y_name`
            )
        )
        def _plot(B, m, n, k, provider):
            tflops = self.output.get_y_vals((B, m, n, k), provider, "tflops")
            return tflops

        save_path = "/tmp/bf16xint16_gemm"

        if not os.path.exists(save_path):
            os.mkdir(save_path)

        _plot.run(show_plots=True, print_data=True, save_path=save_path)
