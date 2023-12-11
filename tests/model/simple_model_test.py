import pyjuice as juice
import torch
import numpy as np
import time
import random

import pyjuice.nodes.distributions as dists
from pyjuice.utils import BitSet
from pyjuice.nodes import multiply, summate, inputs
from pyjuice.model import TensorCircuit

from pyjuice.layer import InputLayer, ProdLayer, SumLayer

import pytest


def simple_model_test():
    
    device = torch.device("cuda:0")

    group_size = 16
    
    with juice.set_group_size(group_size):

        ni0 = inputs(0, num_node_groups = 2, dist = dists.Categorical(num_cats = 4))
        ni1 = inputs(1, num_node_groups = 2, dist = dists.Categorical(num_cats = 4))
        ni2 = inputs(2, num_node_groups = 2, dist = dists.Categorical(num_cats = 6))
        ni3 = inputs(3, num_node_groups = 2, dist = dists.Categorical(num_cats = 6))

        np0 = multiply(ni0, ni1)
        np1 = multiply(ni2, ni3)
        np2 = multiply(ni1, ni2)
        np3 = multiply(ni0, ni1)

        ns0 = summate(np0, np3, num_node_groups = 2)
        ns1 = summate(np1, num_node_groups = 2)
        ns2 = summate(np2, num_node_groups = 2)

        np4 = multiply(ns0, ni2, ni3)
        np5 = multiply(ns1, ni0, ni1)
        np6 = multiply(ns2, ni0, ni3)

        ns = summate(np4, np5, np6, num_node_groups = 1, group_size = 1)

    ns.init_parameters()

    pc = TensorCircuit(ns, layer_sparsity_tol = 0.1)

    ## Test all compilation-related stuff ##

    input_layer = pc.input_layers[0]

    assert torch.all(input_layer.vids[0:32,0] == 0)
    assert torch.all(input_layer.vids[32:64,0] == 1)
    assert torch.all(input_layer.vids[64:96,0] == 2)
    assert torch.all(input_layer.vids[96:128,0] == 3)

    assert torch.all(input_layer.s_pids[:64] == torch.arange(0, 64*4, 4))
    assert torch.all(input_layer.s_pids[64:] == torch.arange(64*4, 64*(4+6), 6))

    assert torch.all(input_layer.s_pfids[:64] == torch.arange(0, 64*4, 4))
    assert torch.all(input_layer.s_pfids[64:] == torch.arange(64*4, 64*(4+6), 6))

    assert torch.all(input_layer.s_mids[0:32] == 0)
    assert torch.all(input_layer.s_mids[32:64] == 1)
    assert torch.all(input_layer.s_mids[64:96] == 2)
    assert torch.all(input_layer.s_mids[96:128] == 3)

    assert torch.all(input_layer.source_nids == torch.arange(0, 128))

    assert input_layer.num_parameters == 64 * (4 + 6)

    assert torch.all(torch.abs(input_layer.params[:64*4].reshape(64, 4).sum(dim = 1) - 1.0) < 1e-4)
    assert torch.all(torch.abs(input_layer.params[64*4:].reshape(64, 6).sum(dim = 1) - 1.0) < 1e-4)

    prod_layer0 = pc.inner_layers[0]

    assert prod_layer0.num_nodes == 4 * 16 * 2
    assert prod_layer0.num_edges == 8 * 16 * 2

    assert torch.all(prod_layer0.partitioned_nids[0] == torch.arange(16, 144, 16))

    assert torch.all(prod_layer0.partitioned_cids[0][0:2,:] == torch.tensor([[16, 48], [32, 64]]))
    assert torch.all(prod_layer0.partitioned_cids[0][2:4,:] == torch.tensor([[16, 48], [32, 64]]))
    assert torch.all(prod_layer0.partitioned_cids[0][4:6,:] == torch.tensor([[80, 112], [96, 128]]))
    assert torch.all(prod_layer0.partitioned_cids[0][6:8,:] == torch.tensor([[48, 80], [64, 96]]))

    assert torch.all(prod_layer0.partitioned_u_cids[0] == torch.tensor([16, 32, 80, 96, 112, 128]))
    assert torch.all(prod_layer0.partitioned_u_cids[1] == torch.tensor([48, 64]))

    assert torch.all(prod_layer0.partitioned_parids[0] == torch.tensor([[16, 48], [32, 64], [80, 112], [96, 128], [80, 0], [96, 0]]))
    assert torch.all(prod_layer0.partitioned_parids[1] == torch.tensor([[16, 48, 112, 0], [32, 64, 128, 0]]))

    sum_layer0 = pc.inner_layers[1]

    assert torch.all(sum_layer0.partitioned_nids[0] == torch.tensor([176, 192, 208, 224]))
    assert torch.all(sum_layer0.partitioned_nids[1] == torch.tensor([144, 160]))

    assert torch.all(sum_layer0.partitioned_cids[0][0,:] == torch.arange(80, 112))
    assert torch.all(sum_layer0.partitioned_cids[0][1,:] == torch.arange(80, 112))
    assert torch.all(sum_layer0.partitioned_cids[0][2,:] == torch.arange(112, 144))
    assert torch.all(sum_layer0.partitioned_cids[0][3,:] == torch.arange(112, 144))
    assert torch.all(sum_layer0.partitioned_cids[1][0,:] == torch.arange(16, 80))
    assert torch.all(sum_layer0.partitioned_cids[1][1,:] == torch.arange(16, 80))

    assert torch.all(sum_layer0.partitioned_pids[0][0,:] == torch.arange(2064, 2576, 16))
    assert torch.all(sum_layer0.partitioned_pids[0][1,:] == torch.arange(2576, 3088, 16))
    assert torch.all(sum_layer0.partitioned_pids[0][2,:] == torch.arange(3088, 3600, 16))
    assert torch.all(sum_layer0.partitioned_pids[0][3,:] == torch.arange(3600, 4112, 16))
    assert torch.all(sum_layer0.partitioned_pids[1][0,:] == torch.arange(16, 1040, 16))
    assert torch.all(sum_layer0.partitioned_pids[1][1,:] == torch.arange(1040, 2064, 16))

    assert torch.all(sum_layer0.partitioned_chids[0] == torch.arange(16, 144, 16))

    assert torch.all(sum_layer0.partitioned_parids[0][:4] == torch.tensor([[144, 160]]))
    assert torch.all(sum_layer0.partitioned_parids[0][4:6] == torch.tensor([[176, 192]]))
    assert torch.all(sum_layer0.partitioned_parids[0][6:8] == torch.tensor([[208, 224]]))

    assert torch.all(sum_layer0.partitioned_parpids[0][0,:] == torch.tensor([16, 1040]))
    assert torch.all(sum_layer0.partitioned_parpids[0][1,:] == torch.tensor([272, 1296]))
    assert torch.all(sum_layer0.partitioned_parpids[0][2,:] == torch.tensor([528, 1552]))
    assert torch.all(sum_layer0.partitioned_parpids[0][3,:] == torch.tensor([784, 1808]))
    assert torch.all(sum_layer0.partitioned_parpids[0][4,:] == torch.tensor([2064, 2576]))
    assert torch.all(sum_layer0.partitioned_parpids[0][5,:] == torch.tensor([2320, 2832]))
    assert torch.all(sum_layer0.partitioned_parpids[0][6,:] == torch.tensor([3088, 3600]))
    assert torch.all(sum_layer0.partitioned_parpids[0][7,:] == torch.tensor([3344, 3856]))

    prod_layer1 = pc.inner_layers[2]

    assert torch.all(prod_layer1.partitioned_nids[0] == torch.arange(16, 112, 16))

    assert torch.all(prod_layer1.partitioned_cids[0][0,:] == torch.tensor([144, 80, 112, 0]))
    assert torch.all(prod_layer1.partitioned_cids[0][1,:] == torch.tensor([160, 96, 128, 0]))
    assert torch.all(prod_layer1.partitioned_cids[0][2,:] == torch.tensor([176, 16, 48, 0]))
    assert torch.all(prod_layer1.partitioned_cids[0][3,:] == torch.tensor([192, 32, 64, 0]))
    assert torch.all(prod_layer1.partitioned_cids[0][4,:] == torch.tensor([176, 16, 112, 0]))
    assert torch.all(prod_layer1.partitioned_cids[0][5,:] == torch.tensor([192, 32, 128, 0]))

    import pdb; pdb.set_trace()


if __name__ == "__main__":
    simple_model_test()
