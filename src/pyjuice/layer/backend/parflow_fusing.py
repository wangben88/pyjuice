from __future__ import annotations

import torch
import torch.nn as nn
import triton
import triton.language as tl


def compile_cum_par_flows_fn(node2tiednodes, MAX_NGROUPS = 2048, BLOCK_SIZE = 2048):

    ngroup2kernel_specs = []
    for source_ns, item in node2tiednodes.items():
        if len(item[0]) > 1: # If the length is 1, then everything is already accumulated in the source node's parflow
            num_par_flows = source_ns._param_flow_range[1] - source_ns._param_flow_range[0]
            pfid_start = source_ns._param_flow_range[0]
            ch_nodes = item[0]

            assert len(ch_nodes) <= MAX_NGROUPS, f"We only support fusing at most {MAX_NGROUPS} groups for parameter flow accumulation. " \
                                                  "Consider setting a greater `max_tied_ns_per_parflow_group` when compiling sum layers."

            ngroup = triton.next_power_of_2(len(ch_nodes))

            ch_pfids = []
            for ch_ns in ch_nodes:
                ch_pfids.append(ch_ns._param_flow_range[0])

            if ngroup not in ngroup2kernel_specs:
                ngroup2kernel_specs[ngroup] = []

            ngroup2kernel_specs[ngroup].append([pfid_start, num_par_flows, ch_pfids])

    kernels_args = []
    for ngroup, kernel_specs in ngroup2kernel_specs.items():

        BLOCK_G = ngroup
        BLOCK_M = BLOCK_SIZE // BLOCK_G

        target_pfids = []
        block_sizes = []
        ch_pfids = []
        for kernel_spec in kernel_specs:
            pfid_start, num_par_flows, ch_pfids = kernel_spec
            for blk_start in range(0, num_par_flows, BLOCK_M):
                blk_end = min(blk_start + BLOCK_M, num_par_flows)
                blk_size = blk_end - blk_start

                ch_pfid = [chid_start + blk_start for chid_start in ch_pfids]
                ch_pfid.extend([0] * (BLOCK_G - len(ch_pfid)))

                target_pfids.append(pfid_start + blk_start)
                block_sizes.append(blk_size)
                ch_pfids.append()

        target_pfids = torch.tensor(target_pfids).contiguous()
        block_sizes = torch.tensor(block_sizes).contiguous()
        ch_pfids = torch.tensor(ch_pfids).contiguous()

        kernels_args.append([target_pfids, block_sizes, ch_pfids, BLOCK_G, BLOCK_M])

    return kernels_args


@triton.jit
def cum_par_flows_kernel(param_flows, target_pfids, block_sizes, ch_pfids, BLOCK_G: tl.constexpr, BLOCK_M: tl.constexpr):

    pid = tl.program_id(axis = 0)

    offs_g = tl.arange(0, BLOCK_G) + pid * BLOCK_G
    offs_chblk = tl.load(ch_pfids + offs_chblk)
    mask_chblk = offs_chblk >= 0

    block_size = tl.load(block_sizes + pid)
    offs_m = tl.arange(0, BLOCK_M)[None,:]
    mask_m = offs_m < block_size

    offs_chs = offs_chblk[:,None] + tl.arange(0, BLOCK_M)[None,:]
    ch_pflows = tl.load(param_flows + offs_chs, mask = mask_chblk[:,None] & mask_m[None,:], other = 0)
    
    tar_pflows = tl.sum(ch_pflows, axis = 0)

    tar_pfid = tl.load(target_pfids + pid)
    tl.store(param_flows + tar_pfid + offs_m, tar_pflows, mask = mask_m)


def compute_cum_par_flows(param_flows, kernels_args):

    for kernel_args in kernels_args:

        target_pfids, block_sizes, ch_pfids, BLOCK_G, BLOCK_M = kernel_args

        grid = (target_pfids.size(0),)

        cum_par_flows_kernel[grid](param_flows, target_pfids, block_sizes, ch_pfids, BLOCK_G, BLOCK_M)

    return None
            