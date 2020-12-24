import torch
import torch.nn as nn
# import torch.optim as optim
# import torch.nn.functional as F
import math
import time
import torch.utils.tensorboard as tb
from os import path
from utils.data_reader import amazon_dataset_iters
from utils import config as conf
from model.att2seq import Decoder, Encoder, Attention, Att2Seq
from nltk.translate.bleu_score import sentence_bleu
from nltk.translate import bleu_score


def test_review_bleu(gts_data, generate_data, vocab, bleu_totals, length, epoch):
    type_wights = [
        [1., 0, 0, 0],
        [.5, .5, 0, 0],
        [1 / 3, 1 / 3, 1 / 3, 0],
        [.25, .25, .25, .25]
    ]
    write_file = './generate_sentence.txt'
    sf = bleu_score.SmoothingFunction()

    # batch first
    gts_idx = torch.transpose(gts_data, 0, 1)
    _, generate_idx = generate_data.max(2)
    generate_idx = torch.transpose(generate_idx, 0, 1)

    gts_sentence = []
    gene_sentence = []
    # detokenize the sentence
    for token_ids in gts_idx:
        current = [vocab.itos[id] for id in token_ids.detach().cpu().numpy()]
        gts_sentence.append(current)
    for token_ids in generate_idx:
        current = [vocab.itos[id] for id in token_ids.detach().cpu().numpy()]
        gene_sentence.append(current)

    with open(write_file, 'at') as f:
        for i in range(len(gts_sentence)):
            print('Epoch: {0} || gt: {1} || gene: {2}'.format(epoch, gts_sentence[i], gene_sentence[i]), file=f)

    # compute bleu score
    assert len(gts_sentence) == len(gene_sentence)
    for i in range(len(gts_sentence)):
        length += 1
        for j in range(4):
            refs = gts_sentence[i]
            sample = gene_sentence[i]
            weights = type_wights[j]
            bleu_totals[j] += bleu_score.sentence_bleu(refs, sample, smoothing_function=sf.method1, weights=weights)

    return bleu_totals, length


def train_epoch(model, iterator, optimizer, criterion, clip):
    model.train()
    epoch_loss = 0.0
    running_loss = 0.0
    for i, batch in enumerate(iterator):
        user = batch.user
        item = batch.item
        rating = batch.rating
        text = batch.text
        optimizer.zero_grad()
        output = model(user, item, rating, text)        # output: (text_length, batch_size, output_dim(=text vocab size))
        output_dim = output.shape[-1]
        output = output[1:].view(-1, output_dim)
        gt_text = text[1:].view(-1)
        # compute loss (cross entropy)
        loss = criterion(output, gt_text)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), clip)
        optimizer.step()
        # statistics
        epoch_loss += loss.item()
        running_loss += loss.item()
    return epoch_loss / len(iterator)


def valid_epoch(model, iterator, criterion, epoch, text_vocab):
    model.eval()
    epoch_loss = 0.0
    bleu_totals = [0.] * 4
    num_reviews = 0
    with torch.no_grad():
        for i, batch in enumerate(iterator):
            user = batch.user
            item = batch.item
            rating = batch.rating
            text = batch.text
            output = model(user, item, rating, text, 0)
            output_dim = output.shape[-1]
            pred_output = output[1:].view(-1, output_dim)
            gt_text = text[1:].view(-1)
            loss = criterion(pred_output, gt_text)
            epoch_loss += loss.item()
            # compute bleu
            bleu_totals, num_reviews = test_review_bleu(text[1:], output, text_vocab, bleu_totals, num_reviews, epoch)
    bleu_totals = [bleu_total / num_reviews for bleu_total in bleu_totals]
    print('[%d] rating BLEU-1: %.3f' % (epoch + 1, bleu_totals[0]))
    print('[%d] rating BLEU-2: %.3f' % (epoch + 1, bleu_totals[1]))

    return epoch_loss / len(iterator)


def epoch_time(start_time, end_time):
    elapsed_time = end_time - start_time
    elapsed_mins = int(elapsed_time / 60)
    elapsed_secs = int(elapsed_time - (elapsed_mins * 60))
    return elapsed_mins, elapsed_secs


def init_weights(m):
    for name, param in m.named_parameters():
        nn.init.uniform_(param.data, -0.08, 0.08)


def init_weights_1(m):
    for name, param in m.named_parameters():
        if 'weight' in name:
            nn.init.normal_(param.data, mean=0, std=0.01)
        else:
            nn.init.constant_(param.data, 0)


def train(args):
    # Load logger
    train_logger, valid_logger = None, None
    if args.log_dir is not None:
        train_logger = tb.SummaryWriter(path.join(args.log_dir, 'train'))
        valid_logger = tb.SummaryWriter(path.join(args.log_dir, 'valid'))

    device = torch.device('cuda') if torch.cuda.is_available() else torch.device('cpu')

    # Loading the dataset
    dataset_folder = './data/Musical_Instruments_5/'
    item_vocab, user_vocab, text_vocab, train_iter, val_iter, test_iter = (
        amazon_dataset_iters(dataset_folder, batch_sizes=(32, 32, 32))
    )

    # Count user and item number
    items_count = len(item_vocab)
    users_count = len(user_vocab)
    vocab_size = len(text_vocab)

    # Load model
    enc = Encoder(users_count, items_count)
    attn = Attention(conf.enc_hid_dim, conf.dec_hid_dim)
    dec = Decoder(vocab_size, conf.word_dim, conf.enc_hid_dim, conf.dec_hid_dim, conf.rnn_layers, conf.dropout, attn)

    model = Att2Seq(enc, dec, device)

    model.to(device)

    model.apply(init_weights)

    optimizer = torch.optim.Adam(model.parameters(), lr=args.learning_rate)
    # TODO: Add learning rate scheduler
    # scheduler = torch.optim.lr_scheduler.MultiStepLR(optimizer, [25, 40], gamma=0.2)

    TEXT_PAD_IDX = text_vocab.stoi['<pad>']

    criterion = nn.CrossEntropyLoss(ignore_index=TEXT_PAD_IDX)

    global_step = 0
    best_valid_loss = float('inf')

    for epoch in range(args.num_epoch):
        start_time = time.time()
        # Training Procedure
        train_loss = train_epoch(model, train_iter, optimizer, criterion, conf.CLIP)
        # Validation Procedure
        valid_loss = valid_epoch(model, val_iter, criterion, epoch, text_vocab)
        end_time = time.time()
        epoch_mins, epoch_secs = epoch_time(start_time, end_time)

        if valid_loss < best_valid_loss:
            best_valid_loss = valid_loss
            torch.save(model.state_dict(), 'att2seq_best.pth')

        print(f'Epoch: {epoch+1:02} | Time: {epoch_mins}m {epoch_secs}s')
        print(f'\tTrain Loss: {train_loss:.3f} | Train PPL: {math.exp(train_loss):7.3f}')
        print(f'\t Val. Loss: {valid_loss:.3f} |  Val. PPL: {math.exp(valid_loss):7.3f}')

    # Testing Procedure
    print('Finished training, start testing ...')
    model.load_state_dict(torch.load('att2seq_best.pth'))
    test_loss = valid_epoch(model, test_iter, criterion)
    print(f'| Test Loss: {test_loss:.3f} | Test PPL: {math.exp(test_loss):7.3f} |')


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()

    parser.add_argument('--log_dir', type=str, default='./logging', help='The path of the logging dir')
    # Put custom arguments here
    parser.add_argument('-n', '--num_epoch', type=int, default=1)
    parser.add_argument('-lr', '--learning_rate', type=float, default=1e-3)
    parser.add_argument('-c', '--continue_training', action='store_true')
    parser.add_argument('-sf', '--save_model_freq', type=int, default=2, help='Frequency of saving model, per epoch')
    parser.add_argument('-s', '--save_dir', type=str, default='./exp', help='The path of experiment model dir')
    parser.add_argument('-b', '--batch_size', type=int, default=64, help='batch size for traning')

    args = parser.parse_args()
    train(args)
