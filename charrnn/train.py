# -*- coding: utf-8 -*-
"""
Module for training CharRNN
"""
from __future__ import print_function

import os
import functools
import operator
import h5py
import json

import numpy as np

from os.path import splitext

from . text import get_text, translate
from . output import print_model, printer
from . const import CHARS, CHAR_IND, IND_CHAR
from . utils import get_window

__all__ = 'gen_batch', 'get_optimzer', 'build_model'


def tweak_lr(optimizer):
    default_values = {
        'nadam': 0.004,
        'adam': 0.001,
        'rmsprop': 0.001,
        'sgd': 0.01
    }
    return default_values[optimizer.lower()]


def get_optimzer(args):
    import keras

    opt_args = dict(clipvalue=4.0, lr=args.lr)

    if os.path.exists(args.model) and args.resume and not args.lr:
        with h5py.File(args.model) as h5file:
            config = json.loads(h5file.attrs['training_config'])
            opt_args = config.get('optimizer_config', {}).get('config', opt_args)

    opt_args['lr'] = args.lr = opt_args.get('lr', None) or tweak_lr(args.optimizer)

    grab = operator.attrgetter(args.optimizer)
    optimizer = grab(keras.optimizers)

    return optimizer(**opt_args)


def gen_batch(text, batch, window):
    """
    Infinitely generate batches of data of size args.batch
    """
    tr, ind = translate(text, batch=batch), 0
    while True:
        try:
            X = np.zeros((batch, window, len(CHARS)), dtype=np.bool)
            y = np.zeros((batch,         len(CHARS)), dtype=np.bool)
            for i in range(batch):
                y[i, tr[i + window + ind]] = True
                for j in range(window):
                    X[i, j, tr[j + i + ind]] = True
            yield X, y
            ind += batch
        except:
            ind = 0


def build_model(args):
    """
    Build a Stateful Stacked LSTM Network with n-stacks specified by args.layers
    """
    from keras import backend as K

    from keras.layers.recurrent import LSTM
    from keras.layers.core import Dense
    from keras.models import Sequential, load_model

    layers = list(reversed(range(1, args.layers)))
    params = dict(return_sequences=True, stateful=True, dropout=args.dropout,
                  batch_input_shape=(args.batch, args.window, len(CHARS)))

    optimizer = get_optimzer(args)

    if os.path.exists(args.model) and args.resume:
        print('Resuming Training')
        args.window = get_window(args.model)
        model = load_model(args.model)
        K.set_value(model.optimizer.lr, args.lr)
    else:
        model = Sequential()

        while layers:
            layers.pop()
            model.add(LSTM(args.batch, **params))
        else:
            # Last Layer is Flat
            del params['return_sequences']
            model.add(LSTM(args.batch, **params))

        model.add(Dense(len(CHARS), name='softmax', activation='softmax'))

        model.compile(loss='categorical_crossentropy',
                      optimizer=optimizer,
                      metrics=['accuracy'])

    return model


def train_val_split(text, args):
    v_split = round((len(text) // args.batch) * (1 - args.split)) * args.batch
    return text[:v_split], text[v_split:]


def get_callbacks(args):
    from keras.callbacks import TensorBoard, CSVLogger

    from . callbacks import CharRNNCheckpoint, AdvancedLRScheduler

    callbacks = [
        AdvancedLRScheduler(monitor=args.monitor, verbose=args.verbose,
                            factor=args.decay, frequency=args.decay_freq),
        CharRNNCheckpoint(args.model, args.window, save_best_only=True,
                          monitor=args.monitor, verbose=args.verbose),
        CSVLogger(os.extsep.join([splitext(args.model)[0], 'csv']), append=bool(args.resume)),
    ]

    if args.log_dir:
        callbacks.append(TensorBoard(log_dir=args.log_dir, histogram_freq=10,
                                     write_grads=True, batch_size=args.batch))
    return callbacks


def run(args):
    """
    Main entry point for training network
    """
    assert args.layers > 0

    # Currying Generator Function
    generator = functools.partial(gen_batch, batch=args.batch, window=args.window)

    # Split Dataset into Train and Validation
    t_train, t_val = train_val_split(get_text(args.datasets), args)

    printer(t_train, t_val, args)

    # Build Model
    model = build_model(args)

    print_model(model, args)

    # Go Get Some Coffee
    model.fit_generator(generator=generator(t_train),
                        steps_per_epoch=len(t_train) // args.batch,
                        validation_data=generator(t_val),
                        validation_steps=len(t_val) // args.batch,
                        epochs=args.epochs,
                        callbacks=get_callbacks(args),
                        use_multiprocessing=True,
                        shuffle=False)
