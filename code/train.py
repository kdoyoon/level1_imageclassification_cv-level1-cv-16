import json
from dataset.dataset import Age_Dataset, Gender_Dataset, Mask_Dataset
from model.models import *
import torch
from torch.utils.data import DataLoader
from tqdm import tqdm
import numpy as np
from sklearn.metrics import f1_score
import os

import random
import torch.backends.cudnn as cudnn
from ema_pytorch import EMA
from optim.sam import SAM

from loss.focal import FocalLossWithSmoothing

import warnings
warnings.filterwarnings(action='ignore')

device = torch.device('cuda') if torch.cuda.is_available() else torch.device('cpu')

cfg = json.load(open("cfg.json", "r"))

torch.manual_seed(cfg["SEED"])
torch.cuda.manual_seed(cfg["SEED"])
torch.cuda.manual_seed_all(cfg["SEED"])
np.random.seed(cfg["SEED"])
cudnn.benchmark = False
cudnn.deterministic = True
random.seed(cfg["SEED"])


def competition_metric(true, pred):
    return f1_score(true, pred, average="macro")

def validation(model, criterion, test_loader, device):
    model.eval()

    model_preds = []
    true_labels = []

    val_loss = []

    with torch.no_grad():
        for img, label in tqdm(iter(test_loader)):
            img, label = img.float().to(device), label.type(torch.LongTensor).to(device)

            model_pred = model(img)

            loss = criterion(model_pred, label)

            val_loss.append(loss.item())

            model_preds += model_pred.argmax(1).detach().cpu().numpy().tolist()
            true_labels += label.detach().cpu().numpy().tolist()

    val_f1 = competition_metric(true_labels, model_preds)
    return np.mean(val_loss), val_f1

def train(mtype, model, optimizer, criterion, train_loader, test_loader, scheduler, device):
    model.to(device)


    best_score = 0
    best_model = None

    for epoch in range(1, cfg[mtype]["EPOCHS"] + 1):
        model.train()
        train_loss = []
        for img, label in tqdm(iter(train_loader)):
            img, label = img.float().to(device), label.type(torch.LongTensor).to(device)

            optimizer.zero_grad()

            model_pred = model(img)
 
            loss = criterion(model_pred, label)  # use this loss for any training statistics
            loss.backward()
            optimizer.first_step(zero_grad=True)

            # second forward-backward pass
            criterion(model(img), label).backward()  # make sure to do a full forward pass
            optimizer.second_step(zero_grad=True)

#             loss = criterion(model_pred, label)
#             loss.backward()
#             optimizer.step(closure)
#             ema.update()

            train_loss.append(loss.item())

        tr_loss = np.mean(train_loss)

        val_loss, val_score = validation(model, criterion, test_loader, device)

        print(
            f'Epoch [{epoch}], Train Loss : [{tr_loss:.5f}] Val Loss : [{val_loss:.5f}] Val F1 Score : [{val_score:.5f}]')

        if scheduler is not None:
            scheduler.step()

        if best_score < val_score:
            best_model = model
            best_score = val_score
            torch.save(best_model, f"exp/{last}/{mtype}/best.pt")

    return best_model


def exp_generator():
    exp = os.listdir("exp")
    exp = [x for x in exp if not x.startswith(".")]
    
    if not exp:
        os.mkdir("exp/0")
        os.mkdir("exp/0/age")
        os.mkdir("exp/0/gender")
        os.mkdir("exp/0/mask")
        last = 0
    else:
        last = list(map(int, exp))
        last.sort()
        last = last[-1]
        last+= 1
        
        os.mkdir(f"exp/{last}")
        os.mkdir(f"exp/{last}/age")
        os.mkdir(f"exp/{last}/gender")
        os.mkdir(f"exp/{last}/mask")
        
    return last


# import pprint
# pprint.pprint(timm.models.list_models())

train_age_dataset = Age_Dataset(cfg)
train_age_loader = DataLoader(train_age_dataset, batch_size = cfg['BATCH_SIZE'], shuffle=True, num_workers=0)
val_age_dataset = Age_Dataset(cfg, val=True)
val_age_loader = DataLoader(val_age_dataset, batch_size=cfg['BATCH_SIZE'], shuffle=False, num_workers=0)

train_gender_dataset = Gender_Dataset(cfg)
train_gender_loader = DataLoader(train_gender_dataset, batch_size = cfg['BATCH_SIZE'], shuffle=True, num_workers=0)
val_gender_dataset = Gender_Dataset(cfg, val=True)
val_gender_loader = DataLoader(val_gender_dataset, batch_size=cfg['BATCH_SIZE'], shuffle=False, num_workers=0)

train_mask_dataset = Mask_Dataset(cfg)
train_mask_loader = DataLoader(train_mask_dataset, batch_size = cfg['BATCH_SIZE'], shuffle=True, num_workers=0)
val_mask_dataset = Mask_Dataset(cfg, val=True)
val_mask_loader = DataLoader(val_mask_dataset, batch_size=cfg['BATCH_SIZE'], shuffle=False, num_workers=0)

last = exp_generator()
# last = 12

scheduler = None

print(">> Age Clasification -----------------------")
model = Age_Model(num_classes=train_age_dataset.num_classes)
criterion = FocalLossWithSmoothing(train_age_dataset.num_classes, 3, 0.1).to(device)
base_optimizer = torch.optim.SGD
optimizer = SAM(model.parameters(), base_optimizer, lr=0.001, momentum=0.9, nesterov = True)
age_model = train("age", model, optimizer, criterion, train_age_loader, val_age_loader, scheduler, device)
print("--------------------------------------------")
torch.cuda.empty_cache()

print(">> Gender Clasification -----------------------")
model = Gender_Model(num_classes=train_gender_dataset.num_classes)
criterion = FocalLossWithSmoothing(train_gender_dataset.num_classes, 2, 0.2).to(device)
base_optimizer = torch.optim.SGD
optimizer = SAM(model.parameters(), base_optimizer, lr=0.001, momentum=0.9, nesterov = True)
gender_model = train("gender", model, optimizer, criterion, train_gender_loader, val_gender_loader, scheduler, device)
print("--------------------------------------------")
torch.cuda.empty_cache()


print(">> Mask Clasification -----------------------")
model = Mask_Model(num_classes=train_mask_dataset.num_classes)
criterion = FocalLossWithSmoothing(train_mask_dataset.num_classes, 2, 0.1).to(device)
base_optimizer = torch.optim.SGD
optimizer = SAM(model.parameters(), base_optimizer, lr=0.001, momentum=0.9, nesterov = True)
mask_model = train("mask", model, optimizer, criterion, train_mask_loader, val_mask_loader, scheduler, device)
print("--------------------------------------------")
torch.cuda.empty_cache()