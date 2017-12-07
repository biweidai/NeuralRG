import os
import sys
sys.path.append(os.getcwd())
import torch
torch.manual_seed(42)
from torch.autograd import Variable
import numpy as np
import matplotlib.pyplot as plt

from model import Gaussian,MLP,RealNVP
from train import Ring2D, Ring5, Wave, Phi4, Mog2, Ising
from train import MCMC

def learn_acc(target, model, Nepochs, Batchsize, Nsteps, Nskips, modelname, alpha=0.0, beta=1.0, lr =1e-3, weight_decay = 0.001,save = True, saveSteps=10):
    LOSS=[]

    sampler = MCMC(target, model, collectdata=True)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=weight_decay)

    dbeta = (1.-beta)/Nepochs

    for epoch in range(Nepochs):
        samples, _,accratio,res, sjd = sampler.run(Batchsize, 0, Nsteps, Nskips)
        beta += dbeta
        sampler.set_beta(beta)

        #print (accratio, type(accratio)) 
        loss = -res.mean() - alpha * sjd.mean() 
        alpha *= 0.98 

        print ("epoch:",epoch, "loss:",loss.data[0], "acc:", accratio, "beta:", beta)
        LOSS.append([loss.data[0], accratio])

        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

        if save and epoch%saveSteps==0:
            saveDict = model.saveModel({})
            torch.save(saveDict, model.name+'/epoch'+str(epoch))

            samples = np.array(samples)
            samples.shape = (Batchsize*Nsteps, -1)
            x = model.sample(1000)
            x = x.cpu().data.numpy()
  
            plt.figure()
            plt.scatter(x[:,0], x[:,-1], alpha=0.5, label='proposals')
            plt.scatter(samples[:,0], samples[:,-2], alpha=0.5, label='samples')
            plt.xlim([-5, 5])
            plt.ylim([-5, 5])
            plt.xlabel('$x_1$')
            plt.ylabel('$x_2$')
            plt.legend()
            plt.savefig(model.name+'/epoch%g.png'%(epoch)) 
            plt.close() 

    return model, LOSS

if __name__=="__main__":
    import h5py
    import subprocess
    import argparse
    parser = argparse.ArgumentParser(description='')
    parser.add_argument("-Nlayers", type=int, default=8, help="")
    parser.add_argument("-Hs", type=int, default=10, help="")
    parser.add_argument("-Ht", type=int, default=10, help="")
    parser.add_argument("-Nepochs", type=int, default=500, help="")
    parser.add_argument("-target", default='ring2d', help="target distribution")
    parser.add_argument("-Batchsize", type=int, default=64, help="")
    parser.add_argument("-cuda", action='store_true', help="use GPU")
    parser.add_argument("-float", action='store_true', help="use float32")
    parser.add_argument("-alpha", type=float, default=0.0, help="sjd term")
    parser.add_argument("-beta", type=float, default=1.0, help="temperature term")
    parser.add_argument("-folder", default='data/',
                    help="where to store results")

    group = parser.add_argument_group('mc parameters')
    group.add_argument("-Ntherm", type=int, default=100, help="")
    group.add_argument("-Nsamples", type=int, default=100, help="")
    group.add_argument("-Nsteps", type=int, default=10, help="steps used in training")
    group.add_argument("-Nskips", type=int, default=10, help="")

    group = parser.add_argument_group('target parameters')
    #Mog2 
    group.add_argument("-offset",type=float, default=2.0,help="offset of mog2")
    #Ising
    group.add_argument("-L",type=int, default=2,help="linear size")
    group.add_argument("-d",type=int, default=1,help="dimension")
    group.add_argument("-K",type=float, default=1.0,help="K")

    args = parser.parse_args()

    if args.target == 'ring2d':
        target = Ring2D()
    elif args.target == 'ring5':
        target = Ring5()
    elif args.target == 'wave':
        target = Wave()
    elif args.target == 'mog2':
        target = Mog2(args.offset)
    elif args.target == 'phi4':
        target = Phi4(4,2,0.15,1.145)
    elif args.target == 'ising':
        target = Ising(args.L, args.d, args.K)
    else:
        print ('what target ?', args.target)
        sys.exit(1)

    modelfolder = 'data/learn_acc'
    cmd = ['mkdir', '-p', modelfolder]
    subprocess.check_call(cmd)

    Nvars = target.nvars 

    sList = [MLP(Nvars//2, args.Hs) for i in range(args.Nlayers)]
    tList = [MLP(Nvars//2, args.Ht) for i in range(args.Nlayers)]

    gaussian = Gaussian([Nvars])

    model = RealNVP([Nvars], sList, tList, gaussian, maskTpye="channel",name = modelfolder,double=not args.float)
    if args.cuda:
        model = model.cuda()

    model, LOSS = learn_acc(target, model, args.Nepochs,args.Batchsize, 
                            args.Nsteps, args.Nskips,
                            'learn_acc', alpha=args.alpha, beta=args.beta)

    sampler = MCMC(target, model, collectdata=True)
    _, measurements, _, _, _= sampler.run(args.Batchsize, args.Ntherm, args.Nsamples, args.Nskips)

    cmd = ['mkdir', '-p', args.folder]
    subprocess.check_call(cmd)
    key = args.folder \
          + args.target \
          + '_Nl' + str(args.Nlayers) \
          + '_Hs' + str(args.Hs) \
          + '_Ht' + str(args.Ht)
    h5filename = key + '_mc.h5'
    print("save at: " + h5filename)
    h5 = h5py.File(h5filename, 'w')
    params = h5.create_group('params')
    params.create_dataset("Nvars", data=target.nvars)
    params.create_dataset("Nlayers", data=args.Nlayers)
    params.create_dataset("Hs", data=args.Hs)
    params.create_dataset("Ht", data=args.Ht)
    params.create_dataset("target", data=args.target)
    params.create_dataset("model", data=model.name)
    results = h5.create_group('results')
    results.create_dataset("obs", data=np.array(measurements))
    results.create_dataset("loss", data=np.array(LOSS))
    h5.close()

    plt.figure()
    LOSS = np.array(LOSS)
    plt.subplot(211)
    plt.plot(LOSS[:, 0], label='loss')
    plt.subplot(212)
    plt.plot(LOSS[:, 1], label='acc')
    plt.xlabel('iterations')

    plt.show()

