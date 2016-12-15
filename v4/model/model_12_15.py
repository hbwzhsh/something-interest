"""
use softmax regression and read data from mongodb
"""
import logging
import time
import numpy as np
import tensorflow as tf
from v4.config import config
from v4.util.load_all_code import load_all_code
from v4.util.mini_batch import batch
from v4.service.construct_train_data import GenTrainData

logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s %(filename)s[line:%(lineno)d] %(levelname)s %(message)s',
                    datefmt='%b %d %Y %H:%M:%S',
                    filename='/home/daiab/log/quantlog.log',
                    filemode='w')
logger = logging.getLogger(__name__)


class LstmModel:
    def __init__(self, session):
        self._session = session

        self.all_stock_code = load_all_code()

        self.loop_code_time = 0

    # def matmul_on_gpu(n):
    #     if n.type == "MatMul":
    #         return "/gpu:0"
    #     else:
    #         return "/cpu:0"

    def load_data(self):
        self.dd_list = GenTrainData(self.all_stock_code, config.time_step).dd_list

    # with tf.device(matmul_on_gpu):
    def build_graph(self):
        """placeholder: drop keep prop"""
        self.rnn_keep_prop = tf.placeholder(tf.float32)
        self.hidden_layer_keep_prop = tf.placeholder(tf.float32)

        """placeholder: train data"""
        self.one_train_data = tf.placeholder(tf.float32, [None, config.time_step, 4])
        self.target_data = tf.placeholder(tf.float32, [None, 2])

        """RNN architecture"""
        cell = tf.nn.rnn_cell.BasicLSTMCell(config.hidden_cell_num,
                                            input_size=[config.batch_size, config.time_step, config.hidden_cell_num])
        cell = tf.nn.rnn_cell.DropoutWrapper(cell, input_keep_prob=1.0, output_keep_prob=self.rnn_keep_prop)

        multi_cell = tf.nn.rnn_cell.MultiRNNCell([cell] * config.hidden_layer_num)
        val, self.states = tf.nn.dynamic_rnn(multi_cell, self.one_train_data, dtype=tf.float32)

        """reshape the RNN output"""
        # val = tf.transpose(val, [1, 0, 2])
        # self.val = tf.gather(val, val.get_shape()[0] - 1)
        dim = config.time_step * config.hidden_cell_num
        self.val = tf.reshape(val, [-1, dim])

        """softmax layer 1"""
        self.weight = tf.Variable(tf.truncated_normal([dim, config.output_cell_num], dtype=tf.float32), name='weight')
        self.bias = tf.Variable(tf.constant(0.0, dtype=tf.float32, shape=[1, config.output_cell_num]), name='bias')

        tmp_value = tf.nn.relu(tf.matmul(self.val, self.weight) + self.bias)
        """softmax layer 1 drop out"""
        tmp_value = tf.nn.dropout(tmp_value, keep_prob=self.hidden_layer_keep_prop)

        """softmax layer 2"""
        self.weight_2 = tf.Variable(tf.truncated_normal([config.output_cell_num, 2], dtype=tf.float32), name='weight_2')
        self.bias_2 = tf.Variable(tf.constant(0.0, dtype=tf.float32, shape=[1, 2]), name='bias_2')
        self.predict_target = tf.matmul(tmp_value, self.weight_2) + self.bias_2

        """Loss function and Optimizer"""
        self.cross_entropy = tf.reduce_mean(
            tf.nn.softmax_cross_entropy_with_logits(self.predict_target, self.target_data))
        self.minimize = tf.train.AdamOptimizer(learning_rate=config.learning_rate).minimize(self.cross_entropy)
        self._session.run(tf.initialize_all_variables())

        """saver"""
        self.saver = tf.train.Saver()

    def train_model(self):
        self.load_data()
        for i in range(config.epochs):
            count = len(self.dd_list) - 1
            while count >= 0:
                dd = self.dd_list[count]
                shuffle_range = list(range(dd.days))
                np.random.shuffle(shuffle_range)

                logger.info("stockCode == %d, epoch == %d", dd.code, i)
                batch_data = batch(batch_size=config.batch_size,
                                   data=dd.train_data[0:dd.train_days],
                                   softmax=dd.softmax[0:dd.train_days])
                feed_dict = {}
                for one_train_data, _, softmax in batch_data:
                    feed_dict = {self.one_train_data: one_train_data,
                                 self.target_data: softmax,
                                 self.rnn_keep_prop: config.rnn_keep_prop,
                                 self.hidden_layer_keep_prop: config.hidden_layer_keep_prop}
                    self._session.run(self.minimize, feed_dict=feed_dict)

                if len(feed_dict) != 0:
                    crossEntropy = self._session.run(self.cross_entropy, feed_dict=feed_dict)
                    logger.info("crossEntropy == %f", crossEntropy)
                self.test(dd)
                count -= 1

            if config.is_save_file == 0:
                save_time = time.strftime("%Y-%m-%d-%H-%M", time.localtime())
                self.saver.save(self._session, "/home/daiab/ckpt/%s.ckpt" % save_time)
                logger.info("save file time: %s", save_time)

    def test(self, dd):
        count_arr, right_arr, prop_step_arr = np.zeros(6), np.zeros(6), np.array([0.5, 0.6, 0.7, 0.8, 0.9, 0.95])
        logger.info("test begin ......")
        for day in range(dd.train_days, dd.days):
            train = [dd.train_data[day]]
            softmax = dd.softmax[day]

            predict = self._session.run(self.predict_target, feed_dict={self.one_train_data: train,
                                                                        self.rnn_keep_prop: 1.0,
                                                                        self.hidden_layer_keep_prop: 1.0})
            predict = np.exp(predict)
            probability = predict / predict.sum()

            max_prob = probability[0][0] if probability[0][0] > probability[0][1] else probability[0][1]
            tmp_bool_index = prop_step_arr <= max_prob
            count_arr[tmp_bool_index] += 1
            if np.argmax(predict) == np.argmax(softmax):
                right_arr[tmp_bool_index] += 1

        logger.info("test ratio>>%s", right_arr / count_arr)
        logger.info("test count>>%s", count_arr)


def run():
    # with tf.Graph().as_default(), tf.Session(config=tf.ConfigProto(log_device_placement=True)) as session:
    with tf.Graph().as_default(), tf.Session() as session:
        config.config_print()
        lstmModel = LstmModel(session)
        lstmModel.build_graph()
        lstmModel.train_model()
        session.close()


if __name__ == '__main__':
    run()