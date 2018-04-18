import torch
from torch import nn
from torch.autograd import Variable


class OmniglotModel(nn.Module):
    """
    A model for Omniglot classification.
    """
    def __init__(self, num_classes):
        nn.Module.__init__(self)

        self.num_classes = num_classes

        self.conv = nn.Sequential(
            # 28 x 28 - 1
            nn.Conv2d(1, 64, 3, 2, 1),
            nn.BatchNorm2d(64),
            nn.ReLU(True),

            # 14 x 14 - 64
            nn.Conv2d(64, 64, 3, 2, 1),
            nn.BatchNorm2d(64),
            nn.ReLU(True),

            # 7 x 7 - 64
            nn.Conv2d(64, 64, 3, 2, 1),
            nn.BatchNorm2d(64),
            nn.ReLU(True),

            # 4 x 4 - 64
            nn.Conv2d(64, 64, 3, 2, 1),
            nn.BatchNorm2d(64),
            nn.ReLU(True),

            # 2 x 2 - 64
        )

        self.classifier = nn.Sequential(
            # 2 x 2 x 64 = 256
            nn.Linear(256, num_classes),
            nn.LogSoftmax(1)
        )

    def forward(self, x):
        out = x.view(-1, 1, 28, 28)
        out = self.conv(out)
        out = out.view(len(out), -1)
        out = self.classifier(out)
        return out

    def clone(self):
        clone = OmniglotModel(self.num_classes)
        clone.load_state_dict(self.state_dict())
        return clone

    def point_grad_to(self, target):
        '''
        Set .grad attribute of each parameter to be proportional
        to the difference between self and target
        '''
        is_cuda = next(self.parameters()).is_cuda
        for p, target_p in zip(self.parameters(), target.parameters()):
            if p.grad is None:
                if is_cuda:
                    p.grad = Variable(torch.zeros(p.size())).cuda()
                else:
                    p.grad = Variable(torch.zeros(p.size()))
            p.grad.data.add_(p.data - target_p.data)


if __name__ == '__main__':
    model = OmniglotModel(20)
    x = Variable(torch.zeros(5, 28*28))
    y = model(x)
    print 'x', x.size()
    print 'y', y.size()

