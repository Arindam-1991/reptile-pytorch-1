import os
import argparse
from tqdm import tqdm
import torch
from torch import nn
from torch.autograd import Variable
from torch.utils.data import DataLoader
from torchvision import transforms
import numpy as np
from tensorboardX import SummaryWriter


from models import OmniglotModel
from omniglot import MetaOmniglotFolder, split_omniglot, ImageCache, transform_image, transform_label


def make_infinite(dataloader):
    while True:
        for x in dataloader:
            yield x

def Variable_(tensor, *args_, **kwargs):
    '''
    Make variable cuda depending on the arguments
    '''
    # Unroll list or tuple
    if type(tensor) in (list, tuple):
        return [Variable_(t, *args_, **kwargs) for t in tensor]
    # Unroll dictionary
    if isinstance(tensor, dict):
        return {key: Variable_(v, *args_, **kwargs) for key, v in tensor.items()}
    # Normal tensor
    variable = Variable(tensor, *args_, **kwargs)
    if args.cuda:
        variable = variable.cuda()
    return variable

# Parsing
parser = argparse.ArgumentParser('Train reptile on omniglot')

# - Training params
parser.add_argument('--classes', default=5, type=int, help='classes in base-task (N-way)')
parser.add_argument('--shots', default=1, type=int, help='shots per class (K-shot)')
parser.add_argument('--train-shots', default=15, type=int, help='train shots')
parser.add_argument('--meta-iterations', default=100000, type=int, help='number of meta iterations')
parser.add_argument('--iterations', default=3, type=int, help='number of base iterations')
parser.add_argument('--test-iterations', default=5, type=int, help='number of base iterations')
parser.add_argument('--batch', default=5, type=int, help='minibatch size in base task')
parser.add_argument('--meta-lr', default=0.8, type=float, help='meta learning rate')
parser.add_argument('--lr', default=1e-3, type=float, help='base learning rate')

# - General params
parser.add_argument('--validation', default=0.1, type=float, help='Percentage of validation')
parser.add_argument('--validate-every', default=100, type=int, help='Meta-evaluation every ... base-tasks')
parser.add_argument('--input', default='omniglot', help='Path to omniglot dataset')
parser.add_argument('--output', help='Where to save models')
parser.add_argument('--cuda', default=1, type=int, help='Use cuda')
parser.add_argument('--logdir', required=True, help='Folder to store everything')
args = parser.parse_args()
if args.train_shots <= 0:
    args.train_shots = args.shots
if os.path.exists(args.logdir):
    os.path.makedirs(args.logdir)
run_dir = args.logdir
if os.path.exists(run_dir):
    os.path.makedirs(run_dir)
logger = SummaryWriter(run_dir)

# Load data
# Resize is done by the MetaDataset because the result can be easily cached
omniglot = MetaOmniglotFolder(args.input, size=(28, 28), cache=ImageCache(),
                              transform_image=transform_image,
                              transform_label=transform_label)
meta_train, meta_test = split_omniglot(omniglot, args.validation)


print 'Meta-Train characters', len(meta_train)
print 'Meta-Test characters', len(meta_test)

# Load model
meta_net = OmniglotModel(args.classes)
if args.cuda:
    meta_net.cuda()

# Loss
cross_entropy = nn.CrossEntropyLoss()
def get_loss(prediction, labels):
    return cross_entropy(prediction, labels)


def do_learning(net, optimizer, train_iter, iterations):

    net.train()
    for iteration in xrange(iterations):
        # Sample minibatch
        data, labels = Variable_(train_iter.next())

        # Forward pass
        prediction = net(data)

        # Get loss
        loss = get_loss(prediction, labels)

        # Backward pass - Update fast net
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

    return loss.data[0]


def do_evaluation(net, test_iter, iterations):

    losses = []
    accuracies = []
    net.eval()
    for iteration in xrange(iterations):
        # Sample minibatch
        data, labels = Variable_(test_iter.next())

        # Forward pass
        prediction = net(data)

        # Get loss
        loss = get_loss(prediction, labels)

        # Get accuracy
        argmax = net.predict(prediction)
        accuracy = (argmax == labels).float().mean()

        losses.append(loss.data[0])
        accuracies.append(accuracy.data[0])

    return np.mean(losses), np.mean(accuracies)


def get_optimizer(net, state=None):
    optimizer = torch.optim.Adam(net.parameters(), lr=args.lr, betas=(0, 0.999))
    if state is not None:
        optimizer.load_state_dict(state)
    return optimizer


# Main loop
meta_optimizer = torch.optim.SGD(meta_net.parameters(), lr=args.meta_lr)
#meta_optimizer = torch.optim.Adam(meta_net.parameters(), lr=args.meta_lr)
info = {}
state = None
for meta_iteration in tqdm(xrange(args.meta_iterations)):

    # Clone model
    net = meta_net.clone()
    optimizer = get_optimizer(net, state)
    # load state of base optimizer?

    # Sample base task from Meta-Train
    train = meta_train.get_random_task(args.classes, args.train_shots)
    train_iter = make_infinite(DataLoader(train, args.batch, shuffle=True))

    # Update fast net
    loss = do_learning(net, optimizer, train_iter, args.iterations)
    state = optimizer.state_dict()  # save optimizer state

    # Update slow net
    meta_net.point_grad_to(net)
    meta_optimizer.step()

    # Meta-Evaluation
    if meta_iteration % args.validate_every == 0:
        for (meta_dataset, mode) in [(meta_train, 'train'), (meta_test, 'val')]:

            train, test = meta_dataset.get_random_task_split(args.classes, train_K=args.shots, test_K=5)  # is that 5 ok?
            train_iter = make_infinite(DataLoader(train, args.batch, shuffle=True))
            test_iter = make_infinite(DataLoader(test, args.batch, shuffle=True))

            # Base-train
            net = meta_net.clone()
            optimizer = get_optimizer(net, state)
            loss = do_learning(net, optimizer, train_iter, args.test_iterations)

            # Base-test: compute meta-loss, which is base-validation error
            meta_loss, meta_accuracy = do_evaluation(net, test_iter, 1)  # only one iteration for eval

            info.setdefault(mode, {})
            info[mode].setdefault('loss', [])
            info[mode]['loss'].append(meta_loss)
            info[mode].setdefault('accuracy', [])
            info[mode]['accuracy'].append(meta_accuracy)

            print '\nMeta-{} loss'.format(mode)
            print 'metaloss', meta_loss
            print 'accuracy', meta_accuracy
            print 'average metaloss', np.mean(info[mode]['loss'])
            print 'average accuracy', np.mean(info[mode]['accuracy'])

            logger.add_scalar('{}_accuracy'.format(mode), meta_accuracy, meta_iteration)
            logger.add_scalar('{}_loss'.format(mode), meta_loss, meta_iteration)

