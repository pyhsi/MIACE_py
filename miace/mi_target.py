import numpy as np
from sklearn.cluster import KMeans
import copy

# default parameters for miTarget
default_parameters = {
    # Set to 0 for MI-SMF, Set to 1 for MI-ACE
    "methodFlag": True,
    # Set to 1 to use global mean and covariance, set to 0 to use negative bag mean and covariance
    "globalBackgroundFlag": False,
    #Type 1 is to use best positive instance based on objective function value,
    #Type 2 clusters the data with k-means and selects the best cluster center as the initial target signature
    "initType": 1,
    # Value used to indicate positive bags, usually 1
    "posLabel": 1,
    # Value used to indicate negative bags, usually 0 or -1
    "negLabel": 0,
    # Maximum number of iterations (rarely used)
    "maxIter": 1000,
    # Percentage of positive data points used to initialize (default = 1)
    "samplePor": 1,
    # If using init3, number of clusters used to initialize (default = 1000)
    "initK": 1000,
    # Number of background clusters (and optimal targets) to be estimated
    "numB": 5 # is this used anywhere?
}


def mi_target(data_bags, labels, parameters=default_parameters):
    """
    MIACE/MISMF Multiple Instance Adaptive Cosine Estimator/Multiple Instance
        Spectral Matched Filter Demo

    Inputs:
      data_bags - 1xB cell array where each cell contains an NxD matrix of N data points of dimensionality D
      (i.e.  N pixels with D spectral bands, each pixel is a row vector).  Total of B cells.

      labels - 1XB array containing the bag level labels corresponding to each cell of the dataBags cell array

      parameters - struct - The struct contains the following fields:
        1. parameters.methodFlag: Set to 0 for MI-SMF, Set to 1 for MI-ACE
        2. parameters.initType: Options are 1 or 2
        3. parameters.globalBackgroundFlag: set to 1 to use global mean and covariance, set to 0 to use negative bag mean and covariance
        4. parameters.posLabel: Value used to indicate positive
        bags, usually 1
        5. parameters.negLabel: Value used to indicate negative bags, usually 0 or -1
        6. parameters.maxIter: Maximum number of iterations (rarely used)
        7. parameters.samplePor: If using init1, percentage of positive data points used to initialize (default = 1)
        8. parameters.initK = 1000; % If using init3, number of clusters used to initialize (default = 1000);
    Outputs:
      opt_target - estimated target concept
      opt_obj_val -  Final Objective Function value
      b_mu - Background Mean to be used in ACE or SMF detector with test data
      sig_inv_half - Square root of background covariance, Use sig_inv_half'*sig_inv_half as covariance in ACE or SMF detector with test data
      init_t - initial target concept
    """
    # print(f'Data bags shape: {data_bags.shape}\nLabels shape: {labels.shape}') # data bag shape is bag x pixel x bands, label is 1 x bag
    num_pos_bags = np.sum(labels == parameters["posLabel"])
    negLabels = (labels == parameters["negLabel"])
    negLabels = np.reshape(negLabels, newshape=(negLabels.shape[1]))

    data = data_bags if parameters["globalBackgroundFlag"] else data_bags[negLabels]
    data = np.vstack([data[i] for i in range(data.shape[0])])
    b_mu = np.mean(data, axis=0) # this is the mean of pixels for a given band, (D,)
    b_cov = np.cov(data.T)

    # Whitening
    print('Whitening...')
    whitened_data, sig_inv_half, s, v = whiten_data(
        b_cov, data_bags, b_mu, parameters)

    # Optimizing
    opt_target, opt_obj_val, init_t = train_target_signature(
        whitened_data, labels, parameters, num_pos_bags)

    # Undo Whitening
    opt_target = undo_whitening(opt_target, s, v)
    init_t = undo_whitening(init_t, s, v)
    return opt_target, opt_obj_val, b_mu, sig_inv_half, init_t


def train_target_signature(whitened_data, labels, parameters, num_pos_bags):
    posLabels = (labels == parameters["posLabel"])
    posLabels = np.reshape(posLabels, newshape=(posLabels.shape[1]))
    negLabels = (labels == parameters["negLabel"])
    negLabels = np.reshape(negLabels, newshape=(negLabels.shape[1]))

    pos_databags = whitened_data[posLabels]
    neg_databags = whitened_data[negLabels]

    init = init_function(parameters['initType'])
    print(f'Initializing with {init.__name__}...')

    init_t, opt_obj_val, pos_bags_max = init(
        pos_databags, neg_databags, parameters)

    opt_target = copy.deepcopy(init_t)

    # from IPython import embed
    # embed()
    n_mean = np.mean(
        [np.mean(neg_databags[i], axis=0).T for i in range(len(neg_databags))], axis=0)

    # Optimizing
    print('Optimizing...')
    n_iter = 1
    threshold_reached = False

    objective_val = np.array([opt_obj_val])
    objective_target = np.array([opt_target])

    while (not threshold_reached and n_iter < parameters['maxIter']):
        n_iter += 1
        p_mean = np.mean(
            pos_bags_max, axis=0) if num_pos_bags > 1 else pos_bags_max

        t = p_mean - n_mean
        opt_target = t / np.linalg.norm(t)

        # Update Objective and Determine the max points in each bag
        opt_obj_val, pos_bags_max = eval_objective_whitened(
            pos_databags, neg_databags, opt_target)

        # see if objective value has been reached
        if np.any(objective_val == opt_obj_val):
            indices = np.linspace(0, n_iter, n_iter)
            loc = indices[objective_val == opt_obj_val][-1]

            # check if threshold has been met
            if np.sum(np.abs(objective_target[loc] - opt_target)) == 0:
                threshold_reached = True
                print("stopped iterating at {} iterations".format(n_iter))

        # Add current iteration's results to array
        np.append(objective_val, opt_obj_val)
        np.append(objective_val, opt_target)

    return opt_target, opt_obj_val, init_t


def eval_objective_whitened(pos_databags, neg_databags, target):
    num_dim = pos_databags[0].shape[1] #number of bands

    pos_conf_bags = np.zeros((pos_databags.shape[0], 1))
    pos_conf_max = np.zeros((pos_databags.shape[0], num_dim))

    for i, pos_data in enumerate(pos_databags):
        pos_conf = np.sum(pos_data*target, axis=1) #(10,)
        idx = np.argmax(pos_conf)
        max_conf = pos_conf[idx]

        pos_conf_bags[i] = max_conf
        pos_conf_max[i] = pos_data[idx]

    neg_conf_bags = np.zeros((neg_databags.shape[0], 1))

    for i, neg_data in enumerate(neg_databags):
        neg_conf = np.sum(neg_data*target, axis=1)
        neg_conf_bags[i] = np.mean(neg_conf, axis=0)

    obj_val = np.mean(pos_conf_bags, axis=0) - np.mean(neg_conf_bags, axis=0)
    return obj_val, pos_conf_max


def init_function(initType=1):
    init_functions = [exhaustive_init, kmeans_init]
    if initType > len(init_functions):
        raise ValueError("Please provide a value of 1 or 2 for initType")
    return init_functions[initType - 1]


def exhaustive_init(pos_databags, neg_databags, parameters):
    # exhaustive search initialization
    # init1

    total_sample = np.sum([pos_databags[bag].shape[0] for bag in range(pos_databags.shape[0])])

    # reshape so all data is in one batch
    pos_data = flatten_databags(pos_databags)

    # get random_samples
    dataset_perm = np.random.permutation(total_sample)
    sample_pts = round(total_sample*parameters['samplePor'])
    pos_data_reduced = pos_data[dataset_perm[:sample_pts]]

    temp_obj_val = np.zeros(pos_data_reduced.shape[0])
    for i, opt_target in enumerate(pos_data_reduced):
        temp_obj_val[i], _ = eval_objective_whitened(
            pos_databags, neg_databags, opt_target)

    # optimal target
    idx = np.argmax(temp_obj_val)

    opt_target = pos_data_reduced[idx]
    opt_target /= np.linalg.norm(opt_target)

    init_t = opt_target

    opt_obj_val, pos_bags_max = eval_objective_whitened(
        pos_databags, neg_databags, opt_target)

    return init_t, opt_obj_val, pos_bags_max


def kmeans_init(pos_databags, neg_databags, parameters):
    # init3
    # K-Means based initialization
    pos_data = flatten_databags(pos_databags)

    if 'C' in parameters:
        C = parameters['C']
    else:
        k_means = KMeans(n_clusters=min(len(pos_data), parameters['initK']), max_iter=parameters['maxIter'])
        C = k_means.fit(pos_data)

    temp_obj_val = [None] * len(C.labels_)

    # Loop through cluster centers
    for i, centroid in enumerate(C.cluster_centers_):
        opt_target = centroid / np.linalg.norm(centroid)
        temp_obj_val[i], _ = eval_objective_whitened(pos_databags, neg_databags, opt_target)

    idx = np.argmax(temp_obj_val)
    opt_target = C.cluster_centers_[idx]
    opt_target /= np.linalg.norm(opt_target)

    init_t = opt_target
    opt_obj_val, pos_bags_max = eval_objective_whitened(
        pos_databags, neg_databags, opt_target)

    return init_t, opt_obj_val, pos_bags_max


def flatten_databags(databags):
    return np.vstack([databags[bag] for bag in range(databags.shape[0])])


def whiten_data(b_cov, data_bags, b_mu, parameters=default_parameters):
    u, s, v = np.linalg.svd(b_cov)
    s_neg_sqrt = (1.0 / np.sqrt(s)) * np.eye(s.shape[0])
    sig_inv_half = np.matmul(s_neg_sqrt, u.T)
    m_minus = np.asarray([data_bags[bag] - b_mu for bag in range(data_bags.shape[0])])
    m_scale = np.asarray([np.matmul(m_minus[bag], sig_inv_half.T) for bag in range(data_bags.shape[0])])

    if parameters['methodFlag']:
        denom = [np.sqrt(np.sum(m_scale[i]*m_scale[i], axis=1)) for i in range(m_scale.shape[0])]
        denom = np.array([np.reshape(denom[bag], (denom[bag].shape[0], 1)) for bag in range(m_scale.shape[0])])
        # print(f'denom after: {denom[0].shape}')
        whitened_data = np.asarray([np.divide(m_scale[bag], denom[bag]) for bag in range(data_bags.shape[0])])

    else:
        denom = 1.0
        whitened_data = np.divide(m_scale, denom)

    return whitened_data, sig_inv_half, s, v


def undo_whitening(whitened_data, s, v):
    s_sqrt = np.sqrt(s)*np.eye(s.shape[0])
    t = np.matmul(np.matmul(whitened_data, s_sqrt), v)
    return t / np.linalg.norm(t)
