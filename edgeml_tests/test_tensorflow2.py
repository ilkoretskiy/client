import tensorflow as tf
import numpy as np
import wandb
import pytest
from absl import flags
from wandb.keras import WandbCallback
import glob


def create_experiment_summary(num_units_list, dropout_rate_list, optimizer_list):
    from tensorboard.plugins.hparams import api_pb2
    from tensorboard.plugins.hparams import summary as hparams_summary
    from google.protobuf import struct_pb2
    num_units_list_val = struct_pb2.ListValue()
    num_units_list_val.extend(num_units_list)
    dropout_rate_list_val = struct_pb2.ListValue()
    dropout_rate_list_val.extend(dropout_rate_list)
    optimizer_list_val = struct_pb2.ListValue()
    optimizer_list_val.extend(optimizer_list)
    return hparams_summary.experiment_pb(
        # The hyperparameters being changed
        hparam_infos=[
            api_pb2.HParamInfo(name='num_units',
                               display_name='Number of units',
                               type=api_pb2.DATA_TYPE_FLOAT64,
                               domain_discrete=num_units_list_val),
            api_pb2.HParamInfo(name='dropout_rate',
                               display_name='Dropout rate',
                               type=api_pb2.DATA_TYPE_FLOAT64,
                               domain_discrete=dropout_rate_list_val),
            api_pb2.HParamInfo(name='optimizer',
                               display_name='Optimizer',
                               type=api_pb2.DATA_TYPE_STRING,
                               domain_discrete=optimizer_list_val)
        ],
        # The metrics being tracked
        metric_infos=[
            api_pb2.MetricInfo(
                name=api_pb2.MetricName(
                    tag='epoch_accuracy'),
                display_name='Accuracy'),
        ]
    )


@pytest.fixture
def model():
    model = tf.keras.models.Sequential()
    model.add(tf.keras.layers.Dense(128, activation="relu"))
    model.add(tf.keras.layers.Dense(10, activation="softmax"))
    model.compile(loss="sparse_categorical_crossentropy",
                  optimizer="sgd", metrics=["accuracy"])
    return model


def test_tfflags(wandb_init_run):
    FLAGS = flags.FLAGS
    flags.DEFINE_float('learning_rate', 0.01, 'Initial learning rate.')
    wandb.config.update(FLAGS)
    assert wandb_init_run.config['learning_rate'] == 0.01


def test_keras(wandb_init_run, model):
    model.fit(np.ones((10, 784)), np.ones((10,)), epochs=1,
              validation_split=0.2, callbacks=[WandbCallback()])
    assert wandb_init_run.history.rows[0]["_step"] == 0
    assert [n.name for n in wandb_init_run.summary["graph"].nodes] == [
        "dense", "dense_1"]


@pytest.mark.mocked_run_manager()
def test_tensorboard(wandb_init_run, model):
    wandb.tensorboard.patch(tensorboardX=False)
    cb = tf.keras.callbacks.TensorBoard(
        histogram_freq=1, log_dir=wandb_init_run.dir)
    model.fit(np.ones((10, 784)), np.ones((10,)), epochs=5,
              validation_split=0.2, callbacks=[cb])
    wandb_init_run.run_manager.test_shutdown()
    assert wandb_init_run.history.rows[0]["_step"] == 0
    assert wandb_init_run.history.rows[-1]["_step"] == 4
    assert wandb_init_run.history.rows[-1]['train/dense_1/kernel_0']


@pytest.mark.mocked_run_manager()
def test_tensorboard_hyper_params(wandb_init_run, model):
    from tensorboard.plugins.hparams import api_pb2
    from tensorboard.plugins.hparams import summary as hparams_summary
    wandb.tensorboard.patch(tensorboardX=False)
    cb = tf.keras.callbacks.TensorBoard(
        histogram_freq=1, log_dir=wandb_init_run.dir)

    class HParams(tf.keras.callbacks.Callback):
        def on_train_begin(self, logs):
            with cb._validation_writer.as_default():
                exp = create_experiment_summary(
                    [16, 32], [0.1, 0.2], ['adam', 'sgd'])
                tf.summary.import_event(tf.compat.v1.Event(
                    summary=exp).SerializeToString())
                summary_start = hparams_summary.session_start_pb(
                    hparams={'num_units': 16, 'dropout_rate': 0.1, 'optimizer': 'adam'})
                summary_end = hparams_summary.session_end_pb(
                    api_pb2.STATUS_SUCCESS)
                tf.summary.import_event(tf.compat.v1.Event(
                    summary=summary_start).SerializeToString())
                tf.summary.import_event(tf.compat.v1.Event(
                    summary=summary_end).SerializeToString())

    model.fit(np.ones((10, 784)), np.ones((10,)), epochs=5,
              validation_split=0.2, callbacks=[cb, HParams()])

    wandb_init_run.run_manager.test_shutdown()
    assert wandb_init_run.history.rows[0]["_step"] == 0
    assert wandb_init_run.history.rows[-1]["_step"] == 4
    print("KEYS", wandb_init_run.history.rows[-1].keys())
    assert wandb_init_run.config["dropout_rate"] == 0.1
    assert wandb_init_run.config["optimizer"] == "adam"