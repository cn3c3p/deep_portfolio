import numpy as np
import pandas as pd
import pandas_datareader.data as web
import datetime
import tflearn as tfl
from sklearn.metrics import mean_absolute_error
import matplotlib.pyplot as plt
import tensorflow as tf
import ipdb
from tensormetrics_helper import tf_metrics
import csv
import pandas

def create_timeseries_dataset(X, look_back, look_ahead):
    """
    X is 1D numpy array of timeseries data
    output: row-normalised sliding window array, target array
    """
    dataX, dataY = [], []
    means, sd = [], []
    for i in range(look_back+look_ahead, X.shape[0]):
        # make sliding window of length look_back + look_ahead
        window = X[(i-look_back-look_ahead):i]
        just_duplicate = window
        # calculate mean and std deviation of first look_back elements
        wm = window[:-look_ahead].mean()
        ws = window[:-look_ahead].std()
        means.append(wm)
        sd.append(ws)
        # rescale entire window
        window = (window - wm) / ws
        # split training data from the target
        dataX.append(window[:-look_ahead])
        dataY.append(window[-1])
    # make numpy arrays of the data
    data, target = np.stack(dataX), np.stack(dataY)
    means, sd = np.array(means), np.array(sd)
    # reshape output to: [samples, time steps, features]
    return means, sd, data.reshape((data.shape[0], data.shape[1], 1)), target.reshape((target.shape[0], 1))




def prepare_data(df, look_back=20, look_ahead=1, n_aug=10, scale=0.1, split=(0.6, 0.2, 0.2)):
    """
    df is a pandas series containing prices
    train, validation, and test sets are generated by splitting df and running a sliding window
    training and validation data are augmented by adding noise, random vertical shifts and linear ramps
    """
    # split into train, validation, and test sets
    train_size = int(df.shape[0] * split[0])
    valid_size = int(df.shape[0] * split[1])
    test_size = df.shape[0] - train_size - valid_size

    # reshape into X=t and Y=t+1
    train_mean, train_sd, trainX, trainY = create_timeseries_dataset(df.values[:train_size], look_back, look_ahead)
    valid_mean, valid_sd, validX, validY = create_timeseries_dataset(df.values[train_size:(train_size+valid_size)], look_back, look_ahead)
    test_mean, test_sd, testX, testY = create_timeseries_dataset(df.values[-test_size:], look_back, look_ahead)

    
    print train_size, valid_size, test_size
    print trainX.shape, trainY.shape
    print validX.shape, validY.shape
    print testX.shape, testY.shape

    return (trainX, trainY), (validX, validY), (testX, testY), (train_mean, train_sd), (valid_mean, valid_sd), (test_mean, test_sd)

def prepare_data_for_trading_model(data, look_back):
    #todo rewrite code to support look_ahead with None
    test_mean, test_sd, testX, testY = create_timeseries_dataset(data, look_back=look_back, look_ahead=1)
    return test_mean, test_sd, testX, testY




def make_network(look_back, batch_size):
    """
    Declare the layer types and sizes
    """
    # create deep neural network with LSTM and fully connected layers
    net = tfl.input_data(shape=[None, look_back, 1], name='input')
    net = tfl.lstm(net, 32, activation='tanh', weights_init='xavier', name='LSTM1')

    net = tfl.fully_connected(net, 20, activation='relu', name='FC1')
    # net = tfl.dropout(net, 0.5)
    net = tfl.fully_connected(net, 40, activation='relu', name='FC2')
    # net = tfl.dropout(net, 0.5)

    net = tfl.fully_connected(net, 1, activation='linear', name='Linear')
    net = tfl.regression(net, batch_size=batch_size, optimizer='adam', learning_rate=0.005, loss='mean_square', name='target')

    return net


def train_network(net, epochs, train, valid):
    """
    Run training for epochs iterations
    train: tuple of (data, target)
    valid: tuple of (data, target)
    """
    # declare model
    model = tfl.DNN(net, tensorboard_dir="./logs_tb", tensorboard_verbose=2)
    # Train model
    model.fit({'input': train[0]}, {'target': train[1]}, n_epoch=epochs,
              validation_set=({'input': valid[0]}, {'target': valid[1]}),
              show_metric=True, shuffle=False)

    model.save('lstm3.tflearn')

    return model


def forecast_one(model, train, valid, test,
                 train_scale, valid_scale, test_scale):

    # Make 1-step forecasts
    trained = model.predict(train[0])
    validated = model.predict(valid[0])
    predicted = model.predict(test[0])

    trained = np.array(trained).flatten()
    validated = np.array(validated).flatten()
    predicted = np.array(predicted).flatten()

    # rescale forecasts and target data (scale[0] is mean, scale[1] is std_dev)
    trained = trained * train_scale[1] + train_scale[0]
    validated = validated * valid_scale[1] + valid_scale[0]
    predicted = predicted * test_scale[1] + test_scale[0]

    trainY = train[1].flatten() * train_scale[1] + train_scale[0]
    validY = valid[1].flatten() * valid_scale[1] + valid_scale[0]
    testY = test[1].flatten() * test_scale[1] + test_scale[0]

    # calculate errors
    mse1 = mean_absolute_error(trainY, trained)
    mse2 = mean_absolute_error(validY, validated)
    mse3 = mean_absolute_error(testY, predicted)
    print ("Mean Absolue Error (MAE) train: %f" % mse1)
    print ("Mean Absolue Error (MAE) valid: %f" % mse2)
    print ("Mean Absolue Error (MAE) test:  %f" % mse3)
    return predicted, testY, (mse1, mse2, mse3)



def clean_up(net, model):
    del model
    del net
    tf.reset_default_graph()

def caculate_error(df, look_back, look_ahead):
    train, valid, test, train_scale, valid_scale, test_scale = prepare_data(df, look_back, look_ahead, n_aug=10, scale=0.1, split=split)
    # set tensor flow params, including random seed
    tfl.config.init_graph(seed=765, log_device=False, num_cores=0, gpu_memory_fraction=0, soft_placement=True)

    # create network and train it
    net = make_network(look_back, batch_size=train[0].shape[0]/2)
    model = train_network(net, epochs, train, valid)

    # calculate errors
    predicted, testY_scaled, (mse1, mse2, mse3) = forecast_one(model, train, valid, test,
                                                   train_scale, valid_scale, test_scale)
    clean_up(net, model)

    return mse1, mse2, mse3


def plot_result(predicted, testY):
    # plot results
    plot_predicted, = plt.plot(predicted, label='predicted', color='red')

    # to have them line up
    plot_test, = plt.plot(testY, label='true', color='blue')
    plt.legend(handles=[plot_predicted, plot_test])
    plt.show()

def load_model_tflearn(look_back, batch_size):
    net = make_network(look_back, batch_size)
    model = tfl.DNN(net, tensorboard_dir="./logs_tb", tensorboard_verbose=0)
    model.load('lstm3.tflearn')
    return model

def forecast_model(data, model, test_sd, test_mean):
    predicted = model.predict(data)
    predicted = np.array(predicted).flatten()
    predicted = predicted * test_sd + test_mean
    return predicted

def read_from_csv(sheet):
    data = pandas.read_csv(sheet)
    return data["CLOSE"][0:5000]

 

epochs = 2
split = (0.8, 0.1, 0.1)
use_csv = True
look_back = 250
look_ahead = 1
train = True
if __name__ == "__main__":
    if use_csv:
        #TODO don't use absolute path
        df = read_from_csv("/Users/deep/development/deep_portfolio/data/NIFTY_sort.csv")
    else:
       start = datetime.datetime(1990, 1, 1)
       end = datetime.datetime(2016, 10, 28)
       data = web.DataReader("^GSPC", 'yahoo', start, end)
       df = data['Adj Close']

    # set batch parameters
    if train:
        # set tensor flow params, including random seed
        train, valid, test, train_scale, valid_scale, test_scale = prepare_data(df, look_back, look_ahead,
                                                                            n_aug=10, scale=0.1, split=split)
        # set tensor flow params, including random seed
        tfl.config.init_graph(seed=765, log_device=False, num_cores=0, gpu_memory_fraction=0, soft_placement=True)

        # create network and train it
        net = make_network(look_back, batch_size=train[0].shape[0]/50)
        model = train_network(net, epochs, train, valid)

        # calculate errors
        predicted, testY_scaled, errors = forecast_one(model, train, valid, test,
                                                   train_scale, valid_scale, test_scale)

        #df = forecast_recursive(model, testX, n_ahead=look_back + 1)
        #print df.tail(30)
        #print predicted

        #plot_result(predicted, testY_scaled)
        # confusion matrix on direction of forecast

        print "DEEP METRICS, PLEASE IGNORE:"
        #TODO -- double check below logic
        true = np.where((testY_scaled[1:] - testY_scaled[:-1])<= 0, 0, 1)
        predicted = np.where((predicted[1:] - testY_scaled[:-1])<= 0, 0, 1)
        result = tf_metrics(true, predicted)
        print "\n--- out of sample stats ---"
        print('Accuracy  %.3f' % (result["accuracy"]))
        print('Precision %.3f' % (result["precision"]))
        print('Recall    %.3f' % (result["recall"]))
        print('\nConfusion Matrix')
        print result["confusion_matrix"]

    #the trading model code can be copied later