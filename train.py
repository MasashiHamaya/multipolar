import argparse
import difflib
import os

import gym
import yaml
from stable_baselines.common import set_global_seeds
from stable_baselines.common.cmd_util import make_atari_env
from stable_baselines.common.vec_env import VecFrameStack, SubprocVecEnv, VecNormalize

from utils import make_env, ALGOS

parser = argparse.ArgumentParser()
parser.add_argument('--env', type=str, nargs='+', default=["CartPole-v1"], help='environment ID(s)')
parser.add_argument('-tb', '--tensorboard-log', help='Tensorboard log dir', default='', type=str)
parser.add_argument('-i', '--trained-agent', help='Path to a pretrained agent to continue training',
                    default='', type=str)
parser.add_argument('--algo', help='RL Algorithm', default='ppo2',
                    type=str, required=False, choices=list(ALGOS.keys()))
parser.add_argument('-n', '--n-timesteps', help='Overwrite the number of timesteps', default=-1,
                    type=int)
parser.add_argument('-f', '--log-folder', help='Log folder', type=str, default='logs')
parser.add_argument('--seed', help='Random generator seed', type=int, default=0)
args = parser.parse_args()

env_ids = args.env

registered_envs = set(gym.envs.registry.env_specs.keys())

for env_id in env_ids:
    # If the environment is not found, suggest the closest match
    if env_id not in registered_envs:
        closest_match = difflib.get_close_matches(env_id, registered_envs, n=1)[0]
        raise ValueError('{} not found in gym registry, you maybe meant {}?'.format(env_id, closest_match))

set_global_seeds(args.seed)

for env_id in env_ids:
    tensorboard_log = None if args.tensorboard_log == '' else args.tensorboard_log + '/' + env_id

    is_atari = False
    if 'NoFrameskip' in env_id:
        is_atari = True

    print("=" * 10, env_id, "=" * 10)

    # Load hyperparameters from yaml file
    with open('hyperparams/{}.yml'.format(args.algo), 'r') as f:
        if is_atari:
            hyperparams = yaml.load(f)['atari']
        else:
            hyperparams = yaml.load(f)[env_id]

    n_envs = hyperparams.get('n_envs', 1)
    # Should we overwrite the number of timesteps?
    if args.n_timesteps > 0:
        n_timesteps = args.n_timesteps
    else:
        n_timesteps = int(hyperparams['n_timesteps'])

    normalize = False
    if 'normalize' in hyperparams.keys():
        normalize = hyperparams['normalize']
        del hyperparams['normalize']

    # Delete keys so the dict can be pass to the model constructor
    if 'n_envs' in hyperparams.keys():
        del hyperparams['n_envs']
    del hyperparams['n_timesteps']

    # Create the environment and wrap it if necessary
    if is_atari:
        print("Using Atari wrapper")
        env = make_atari_env(env_id, num_env=n_envs, seed=0)
        # Frame-stacking with 4 frames
        env = VecFrameStack(env, n_stack=4)
    elif args.algo in ['dqn', 'ddpg']:
        env = gym.make(env_id)
    else:
        env = SubprocVecEnv([make_env(env_id, i) for i in range(n_envs)])
        if normalize:
            print("Normalizing input and return")
            env = VecNormalize(env)

    if args.trained_agent.endswith('.pkl') and os.path.isfile(args.trained_agent):
        # Continue training
        print("Loading pretrained agent")
        # Policy should not be changed
        del hyperparams['policy']
        model = ALGOS[args.algo].load(args.trained_agent, env=env,
                                      tensorboard_log=tensorboard_log, verbose=1, **hyperparams)

        exp_folder = args.trained_agent.split('.pkl')[0]
        if os.path.isdir(exp_folder):
            print("Loading saved running average")
            env.load_running_average(exp_folder)
    else:
        # Train an agent from scratch
        model = ALGOS[args.algo](env=env, tensorboard_log=tensorboard_log, verbose=1, **hyperparams)
    
    model.learn(n_timesteps)

    # Save trained model
    os.makedirs("{}/{}/".format(args.log_folder, args.algo), exist_ok=True)
    model.save("{}/{}/{}".format(args.log_folder, args.algo, env_id))
    if normalize:
        path = "{}/{}/{}".format(args.log_folder, args.algo, env_id)
        os.makedirs(path, exist_ok=True)
        # Important: save the running average, for testing the agent we need that normalization
        env.save_running_average(path)