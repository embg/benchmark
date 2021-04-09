
# Generated by gen_hf_generative.py
import torch
import torch.optim as optim
import torchvision.models as models
from ...util.model import BenchmarkModel
from torchbenchmark.tasks import NLP
from transformers import *
from datasets import load_dataset

class Model(BenchmarkModel):
    task = NLP.LANGUAGE_MODELING

    def __init__(self, device=None, jit=False):
        super().__init__()
        self.device = device
        self.jit = jit


        config = ReformerConfig()
        self.model = AutoModelForMaskedLM.from_config(config).to(device)
        self.optimizer = optim.Adam(self.model.parameters(), lr=0.001)

        input_ids = torch.randint(0, config.vocab_size, (8, 4096)).to(device)
        decoder_ids = torch.randint(0, config.vocab_size, (8, 4096)).to(device)

        eval_context = torch.randint(0, config.vocab_size, (1, 4096)).to(device)

        self.train_inputs = {'input_ids': input_ids, 'labels': decoder_ids}
        self.eval_inputs = {'input_ids': eval_context, 'labels': eval_context}

    def get_module(self):
        if self.jit:
            raise NotImplementedError()
        return self.model, self.eval_inputs

    def train(self, niter=3):
        if self.jit:
            raise NotImplementedError()
        self.model.train()
        for _ in range(niter):
            outputs = self.model(**self.train_inputs)
            loss = outputs.loss
            loss.backward()
            self.optimizer.step()

    def eval(self, niter=1):
        if self.jit:
            raise NotImplementedError()
        self.model.eval()
        with torch.no_grad():
            for _ in range(niter):
                out = self.model(**self.eval_inputs)


if __name__ == "__main__":
    import time
    m = Model(device="cuda")
    module, example_inputs = m.get_module()

    m.train(niter=1)
    torch.cuda.synchronize()

    begin = time.time()
    m.train(niter=1)
    torch.cuda.synchronize()
    print(time.time()-begin)

    begin = time.time()
    m.eval(niter=1)
    torch.cuda.synchronize()
    print(time.time()-begin)
    