import os
import sys
import time

import fire
import torch
import torch.nn as nn

from data_loader import DataLoader
from prepro import normalize_strings, filter_inputs, unicode_to_ascii
from vocab import Vocab
import attentions
import mmt
from mmt import MMTNetwork
from bleu import compute_bleu


MAX_LEN = 15
HIDDEN_DIM = 512
EMB_DIM = 512
ENC_SEQ_LEN = 14 * 14
ENC_DIM = 512
EPOCHS = 100
BATCH_SIZE = 4
CLIP_VAL = 1
TEACHER_FORCE_RAT = 1.0
WEIGHT_DECAY=0.0
LEARNING_RATE=0.001

DEVICE = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
print("DEVICE:\t", DEVICE)

def run(train_feats, 
    train_caps, 
    train_src_caps,
    val_src_caps,
    val_feats=None, 
    val_caps=None, 
    train_prefix="",
    val_prefix="",
    epochs=EPOCHS,
    batch_size=BATCH_SIZE,
    max_seq_len=MAX_LEN,
    hidden_dim=HIDDEN_DIM,
    emb_dim=EMB_DIM,
    enc_seq_len=ENC_SEQ_LEN,
    enc_dim=ENC_DIM,
    clip_val=CLIP_VAL,
    teacher_force=TEACHER_FORCE_RAT,
    dropout_p=0.1,
    attn_activation="relu",
    epsilon=0.0005,
    weight_decay=WEIGHT_DECAY,
    lr=LEARNING_RATE,
    early_stopping=False,
    scheduler=None,
    attention=1,
    decoder=2,
    deep_out=False,
    checkpoint="",
    out_dir="Pytorch_Exp_Out"):

    if decoder == 1:
        decoder = mmt.AttentionDecoder_1
    elif decoder == 2:
        decoder = mmt.AttentionDecoder_2
    elif decoder == 3:
        decoder = mmt.AttentionDecoder_3
    elif decoder == 4:
        decoder = mmt.AttentionDecoder_4

    if attention == 1:
        attention = attentions.AdditiveAttention
    elif attention == 2:
        attention = attentions.GeneralAttention
    elif attention == 3:
        attention = attentions.ScaledGeneralAttention

    train(train_feats=train_feats, train_caps=train_caps, val_feats=val_feats, 
        val_caps=val_caps, train_src_caps=train_src_caps, val_src_caps=val_src_caps, 
        train_prefix=train_prefix, 
        val_prefix=val_prefix, epochs=epochs, batch_size=batch_size, max_seq_len=max_seq_len, 
        hidden_dim=hidden_dim, emb_dim=emb_dim,
        enc_seq_len=enc_seq_len, enc_dim=enc_dim, clip_val=clip_val,
        teacher_force=teacher_force, dropout_p=dropout_p, 
        attn_activation=attn_activation, epsilon=epsilon, 
        weight_decay=weight_decay, lr=lr, early_stopping=early_stopping, 
        scheduler=scheduler, attention=attention, deep_out=deep_out, decoder=decoder, 
        checkpoint=checkpoint, out_dir=out_dir)


def train(train_feats, 
    train_caps, 
    val_feats, 
    val_caps,
    train_src_caps,
    val_src_caps,
    train_prefix="",
    val_prefix="",
    epochs=EPOCHS,
    batch_size=BATCH_SIZE,
    max_seq_len=MAX_LEN,
    hidden_dim=HIDDEN_DIM,
    emb_dim=EMB_DIM,
    enc_seq_len=ENC_SEQ_LEN,
    enc_dim=ENC_DIM,
    clip_val=CLIP_VAL,
    teacher_force=TEACHER_FORCE_RAT,
    dropout_p=0.1,
    attn_activation="relu",
    epsilon=0.0005,
    weight_decay=WEIGHT_DECAY,
    lr=LEARNING_RATE,
    early_stopping=True,
    scheduler="step",
    attention=None,
    deep_out=False,
    decoder=None,
    checkpoint="",
    out_dir="Pytorch_Exp_Out"):
    
    print("EXPERIMENT START ", time.asctime())

    if not os.path.exists(out_dir):
        os.mkdir(out_dir)

    # 1. Load the data

    train_captions = open(train_caps, mode='r', encoding='utf-8') \
        .read().strip().split('\n')
    train_src_captions = open(train_src_caps, mode='r', encoding='utf-8') \
        .read().strip().split('\n')
    train_features = open(train_feats, mode='r').read().strip().split('\n')
    train_features = [os.path.join(train_prefix, z) for z in train_features]    
    
    assert len(train_captions) == len(train_features)

    if val_caps:
        val_captions = open(val_caps, mode='r', encoding='utf-8') \
            .read().strip().split('\n')
        val_src_captions = open(val_src_caps, mode='r', encoding='utf-8') \
            .read().strip().split('\n')

        val_features = open(val_feats, mode='r').read().strip().split('\n')
        val_features = [os.path.join(val_prefix, z) for z in val_features]

        assert len(val_captions) == len(val_features)
    
    # 2. Preprocess the data

    train_captions = normalize_strings(train_captions)
    train_src_captions = normalize_strings(train_src_captions)
    train_data = list(zip(train_captions, train_features, train_src_captions))
    train_data = filter_inputs(train_data)
    print("Total training instances: ", len(train_data))

    if val_caps:
        val_captions = normalize_strings(val_captions)
        val_src_captions = normalize_strings(val_src_captions)

        val_data = list(zip(val_captions, val_features, val_src_captions))
        val_data = filter_inputs(val_data)
        print("Total validation instances: ", len(val_data))
    
    vocab_src = Vocab()
    vocab_src.build_vocab(map(lambda x: x[2], train_data), max_size=10000)
    vocab_src.save(path=os.path.join(out_dir, 'vocab_src.txt'))
    print("Source vocabulary size: ", vocab_src.n_words)

    vocab_tgt = Vocab()
    vocab_tgt.build_vocab(map(lambda x: x[0], train_data), max_size=10000)
    vocab_tgt.save(path=os.path.join(out_dir, 'vocab_tgt.txt'))
    print("Target vocabulary size: ", vocab_tgt.n_words)

    # 3. Initialize the network, optimizer & loss function

    net = MMTNetwork(
        src_emb_dim=emb_dim,
        tgt_emb_dim=emb_dim,
        enc_dim=hidden_dim,
        dec_dim=hidden_dim,
        src_dim=vocab_src.n_words, 
        out_dim=vocab_tgt.n_words,
        img_attn_dim=512,
        src_cap_attn_dim=512,
        sos_token=0, eos_token=1, pad_token=2,
        teacher_forcing_rat=teacher_force,
        max_seq_len=max_seq_len,
        dropout_p=dropout_p, deep_out=deep_out,
        attention=attention, decoder=decoder)
    net.to(DEVICE)

    if checkpoint:
        net.load_state_dict(torch.load(checkpoint))
    
    optimizer = torch.optim.Adam(net.parameters(), lr=lr, weight_decay=weight_decay)
    loss_function = nn.NLLLoss()

    scheduler = set_scheduler(scheduler, optimizer)

    # 4. Train

    prev_val_l = sys.maxsize
    total_instances = 0
    total_steps = 0
    train_loss_log = []
    train_loss_log_batches = []
    train_penalty_log = []
    val_loss_log = []
    val_loss_log_batches = []
    prev_bleu = sys.maxsize
    bleu_log = []

    train_data = DataLoader(captions_src=map(lambda x: x[2], train_data),
        captions_tgt=map(lambda x: x[0], train_data),
        sources=map(lambda x: x[1], train_data), batch_size=batch_size, 
        vocab_tgt=vocab_tgt, vocab_src=vocab_src, max_seq_len=max_seq_len)

    if val_caps:
        val_data = DataLoader(captions_src=map(lambda x: x[2], val_data),
        captions_tgt=map(lambda x: x[0], val_data),
            sources=map(lambda x: x[1], val_data), batch_size=batch_size, 
            vocab_tgt=vocab_tgt, vocab_src=vocab_src, max_seq_len=max_seq_len)

    training_start_time = time.time()

    for e in range(1, epochs + 1):
        print("Epoch ", e)

        tfr = _teacher_force(epochs, e, teacher_force)

        # train one epoch
        train_l, inst, steps, t, l_log, pen = train_epoch(model=net, loss_function=loss_function,
            optimizer=optimizer, data_iter=train_data, max_len=max_seq_len, clip_val=clip_val,
            epsilon=epsilon, teacher_forcing_rat=tfr)
        
        if scheduler is not None:
            scheduler.step()

        # epoch logs
        print("Training loss:\t", train_l)
        print("Instances:\t", inst)
        print("Steps:\t", steps)
        hours = t // 3600
        mins = (t % 3600) // 60
        secs = (t % 60)
        print("Time:\t{0}:{1}:{2}".format(hours, mins, secs))
        total_instances += inst
        total_steps += steps
        train_loss_log.append(train_l)
        train_loss_log_batches += l_log
        train_penalty_log.append(pen)
        print()


        # evaluate
        if val_caps:
            val_l, l_log, bleu = evaluate(model=net, loss_function=loss_function, 
                data_iter=val_data, max_len=max_seq_len, epsilon=epsilon)

            # validation logs
            print("Validation loss: ", val_l)
            print("Validation BLEU-4: ", bleu)
            if bleu > prev_bleu:
                torch.save(net.state_dict(), os.path.join(out_dir, 'net.pt'))
            val_loss_log.append(val_l)
            val_loss_log_batches += l_log
            bleu_log.append(bleu)


        #sample model
        print("Sampling training data...")
        print()
        samples = sample(net, train_data, vocab_tgt, samples=3, max_len=max_seq_len)
        for t, s in samples:
            print("Target:\t", unicode_to_ascii(t))
            print("Predicted:\t", unicode_to_ascii(s))
            print()

        if val_caps:
            print("Sampling validation data...")
            print()
            samples = sample(net, val_data, vocab_tgt, samples=3, max_len=max_seq_len)
            for t, s in samples:
                print("Target:\t", unicode_to_ascii(t))
                print("Predicted:\t", unicode_to_ascii(s))
                print()

        if val_caps:
            # If the validation loss after this epoch increased from the
            # previous epoch, wrap training.
            if prev_bleu > bleu and early_stopping:
                print("\nWrapping training after {0} epochs.\n".format(e + 1))
                break

            prev_val_l = val_l
            prev_bleu = bleu



    # Experiment summary logs.
    tot_time = time.time() - training_start_time
    hours = tot_time // 3600
    mins = (tot_time % 3600) // 60
    secs = (tot_time % 60)
    print("Total training time:\t{0}:{1}:{2}".format(hours, mins, secs))
    print("Total training instances:\t", total_instances)
    print("Total training steps:\t", total_steps)
    print()

    _write_loss_log("train_loss_log.txt", out_dir, train_loss_log)
    _write_loss_log("train_loss_log_batches.txt", out_dir, train_loss_log_batches)
    _write_loss_log("train_penalty.txt", out_dir, train_penalty_log)

    if val_caps:
        _write_loss_log("val_loss_log.txt", out_dir, val_loss_log)
        _write_loss_log("val_loss_log_batches.txt", out_dir, val_loss_log_batches)
        _write_loss_log("val_bleu4_log.txt", out_dir, bleu_log)

    print("EXPERIMENT END ", time.asctime())

def train_epoch(model, loss_function, optimizer, data_iter, max_len=MAX_LEN, 
    clip_val=CLIP_VAL, epsilon=0.0005, teacher_forcing_rat=None):
    """Trains the model for one epoch.

    Returns:
        The epoch loss, number of instances processed, number of optimizer 
        steps performed, duration of the epoch, list of losses for each batch.
    """

    # set the network to training mode
    model.train()

    total_loss = 0
    loss_log = []
    num_instances = 0
    num_steps = 0
    total_penalty = 0
    start_time = time.time()

    for batch in data_iter:
        
        src_caps, img_fts, tgt_caps, batch_size = batch
        src_caps, img_fts, tgt_caps = src_caps.to(DEVICE), img_fts.to(DEVICE), tgt_caps.to(DEVICE)
        
        optimizer.zero_grad()
        y, att_weights = model(source_captions=src_caps,
            image_features=img_fts,
            target_captions=tgt_caps,
            max_len=max_len,
            teacher_forcing_rat=teacher_forcing_rat)
        
        y = y.permute(1, 2, 0)
        tgt_caps = tgt_caps.squeeze(2).permute(1, 0)
        
        loss, penalty = loss_func(loss_function, y, tgt_caps, att_weights, epsilon)
        loss.backward()

        norm = torch.nn.utils.clip_grad_norm_(model.parameters(), clip_val)
        optimizer.step()

        l = loss.item()
        total_loss += l
        total_penalty += 0 if penalty is None else penalty.item()
        loss_log.append(l / batch_size)
        num_instances += batch_size
        num_steps += 1
    
    epoch_time = time.time() - start_time
    f_loss = total_loss / num_instances
    f_penalty = total_penalty / num_instances
    return f_loss, num_instances, num_steps, epoch_time, loss_log, f_penalty

def evaluate(model, loss_function, data_iter, max_len=MAX_LEN, epsilon=0.0005):
    """Computes loss on validation data.

    Returns:
        The loss on the dataset, a list of losses for each batch.
    """

    loss = 0
    loss_log = []
    num_instances = 0

    captions = []
    references = []

    with torch.no_grad():
        # set the network to evaluation mode
        model.eval()
    
        for batch in data_iter:
            i, f, t, batch_size = batch
            i, f, t = i.to(DEVICE), f.to(DEVICE), t.to(DEVICE)
            y, att_w = model(i, f, None, max_len=max_len)
            y = y.permute(1, 2, 0)
            t = t.squeeze(2).permute(1, 0)
        
            l, _ = loss_func(loss_function, y, t, att_w, epsilon)

            loss += l.item()
            loss_log.append(l.item() / batch_size)
            num_instances += batch_size

            # decode
            y = y.permute(0, 2, 1)
            _, topi = y.topk(1, dim=2)
            topi = topi.detach().squeeze(2)
            t = t.detach()

            for j in range(batch_size):
                captions.append(data_iter.vocab_tgt.tensor_to_sentence(topi[j]))
                references.append([data_iter.vocab_tgt.tensor_to_sentence(t[j])])

    bleu = compute_bleu(reference_corpus=references, translation_corpus=captions)[0]
    return (loss / num_instances), loss_log, bleu

def sample(model, data_iter, vocab, samples=1, max_len=MAX_LEN, shuffle=True):
    """Samples from the model.

    Returns:
        A list of tuples of target caption and generated caption.
    """

    if not shuffle:
        data_iter.shuffle = False
    
    samples_left = samples
    results = []

    with torch.no_grad():
        # set the network to evaluation mode
        model.eval()

        for batch in data_iter:
            i, f, t, batch_size = batch
            i, f, t = i.to(DEVICE), f.to(DEVICE), t.to(DEVICE)

            y, _ = model(i, f, None, max_len=max_len)
            # y : [max_len, batch, vocab_dim]
            y = y.permute(1, 0, 2)
            _, topi = y.topk(1, dim=2)
            # topi : [batch, max_len, 1]
            topi = topi.detach().squeeze(2)
            # t : [max_len, batch, 1]
            t = t.squeeze(2).permute(1, 0)

            for i in range(min(samples_left, batch_size)):
                s = ' '.join(vocab.tensor_to_sentence(topi[i]))
                tr = ' '.join(vocab.tensor_to_sentence(t[i]))
                results.append((tr, s))
            samples_left -= (i + 1)
            if samples_left == 0: break
    
    if not shuffle:
        data_iter.shuffle = True

    return results

def infere(model, data_iter, vocab, max_len=MAX_LEN):
    """Perform inference with the model.

    Returns:
        A list generated caption.
    """

    with torch.no_grad():
        # set the network to evaluation mode
        model.eval()
 
        results = []

        for batch in data_iter:
            inputs, targets, batch_size = batch
            inputs, targets = inputs.to(DEVICE), targets.to(DEVICE)

            y, _ = model(features=inputs, targets=None, max_len=max_len)

            # y : [max_len, batch, vocab_dim]
            y = y.permute(1, 0, 2)
            _, topi = y.topk(1, dim=2)
        
            # topi : [batch, max_len, 1]
            topi = topi.detach().squeeze(2)

            for i in range(batch_size):
                s = vocab.tensor_to_sentence(topi[i])
                results.append(s)
    
    return results

def loss_func(loss, outputs, targets, att_weigths, epsilon=0.0005):
    l = loss(input=outputs, target=targets)

    if epsilon == 0:
        return (l, None)

    penalty = 1 - torch.sum(att_weigths, dim=0)
    penalty = penalty.pow(exponent=2).sum(dim=1)
    penalty = torch.sum(epsilon * penalty)
    
    l = l + penalty
    return l, penalty

def _write_loss_log(out_f, out_dir, log):
    with open(os.path.join(out_dir, out_f), mode='w') as f:
        for l in log:
            f.write("{0}\n".format(l))

def _teacher_force(total_epochs, epoch, teacher_forcing_start):
    return teacher_forcing_start

def set_scheduler(scheduler, optimizer):
    if scheduler == "step":
        return torch.optim.lr_scheduler.StepLR(optimizer, step_size=5, gamma=0.1)
    return None


if __name__ == "__main__":
    fire.Fire(run)
