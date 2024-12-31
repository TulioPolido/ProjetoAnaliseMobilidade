from collections import OrderedDict
from typing import Dict, Tuple
from flwr.common import NDArrays, Scalar

import torch
import flwr as fl
import random
import time
import hashlib

from model import Net, train, test
from blockchain import Blockchain

# Global variables
current_weights = {}
globalchain = Blockchain(difficulty=5, save_to_file=True)


class FlowerClient(fl.client.NumPyClient):
    """Define a Flower Client."""

    def __init__(
        self, trainloader, vallodaer, num_classes, difficulty, use_blockchain
    ) -> None:
        super().__init__()

        # the dataloaders that point to the data associated to this client
        self.trainloader = trainloader
        self.valloader = vallodaer
        self.code = random.randint(10000, 20000)
        # a model that is randomly initialised at first
        self.model = Net(num_classes)

        # figure out if this client has access to GPU support or not
        self.device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
        self.hash = 0
        self.difficulty = difficulty
        self.use_blockchain = use_blockchain

    def set_parameters(self, parameters):
        """Receive parameters and apply them to the local model."""
        params_dict = zip(self.model.state_dict().keys(), parameters)

        state_dict = OrderedDict({k: torch.Tensor(v) for k, v in params_dict})

        self.model.load_state_dict(state_dict, strict=True)

    def get_parameters(self, config: Dict[str, Scalar]):
        """Extract model parameters and return them as a list of numpy arrays."""

        return [val.cpu().numpy() for _, val in self.model.state_dict().items()]

    def fit(self, parameters, config):
        try:
            """Train model received by the server (parameters) using the data.

            that belongs to this client. Then, send it back to the server.
            """
            init = time.time()
            print("Client: ")
            # copy parameters sent by the server into client's local model
            self.set_parameters(parameters)

            # fetch elements in the config sent by the server. Note that having a config
            # sent by the server each time a client needs to participate is a simple but
            # powerful mechanism to adjust these hyperparameters during the FL process. For
            # example, maybe you want clients to reduce their LR after a number of FL rounds.
            # or you want clients to do more local epochs at later stages in the simulation
            # you can control these by customising what you pass to `on_fit_config_fn` when
            # defining your strategy.
            lr = config["lr"]
            momentum = config["momentum"]
            epochs = config["local_epochs"]

            # a very standard looking optimiser
            optim = torch.optim.SGD(self.model.parameters(), lr=lr, momentum=momentum)
            # do local training. This function is identical to what you might
            # have used before in non-FL projects. For more advance FL implementation
            # you might want to tweak it but overall, from a client perspective the "local
            # training" can be seen as a form of "centralised training" given a pre-trained
            # model (i.e. the model received from the server)
            train(self.model, self.trainloader, optim, epochs, self.device)
            # Save local weights to the global `current_weights`
            if self.use_blockchain:
                current_weights[self.code] = self.get_parameters({})
                if len(current_weights) == 10:
                    self.aggregate_and_save_to_blockchain()

            end = time.time()
            total_time = end - init
            print(f"Client {self.code} | Time: {total_time}")
            # Flower clients need to return three arguments: the updated model, the number
            # of examples in the client (although this depends a bit on your choice of aggregation
            # strategy), and a dictionary of metrics (here you can add any additional data, but these
            # are ideally small data structures)
            return self.get_parameters({}), len(self.trainloader), {}
        except:
            print("Error in client fit")
            return parameters, 0, {}

    def evaluate(self, parameters: NDArrays, config: Dict[str, Scalar]):
        try:
            self.set_parameters(parameters)

            loss, accuracy = test(self.model, self.valloader, self.device)

            return float(loss), len(self.valloader), {"accuracy": accuracy}
        except:
            print("Error in client evaluate")
            return 0.0, 0, {}

    def aggregate_and_save_to_blockchain(self):
        try:
            """Perform FedAvg and save the averaged model to the blockchain."""
            global current_weights, globalchain

            # Perform Federated Averaging
            print("Performing FedAvg on client weights...")
            aggregated_weights = self.perform_fedavg(current_weights)

            # Save averaged model to the blockchain
            block_data = {"model_weights": aggregated_weights}
            globalchain.mine_block(data=block_data)
            print(
                f"Averaged model saved to blockchain in block {len(globalchain.chain)}"
            )

            # Reset current_weights for the next round
            current_weights = {}
        except:
            print("Error in aggregate_and_save_to_blockchain")

    @staticmethod
    def perform_fedavg(weights_dict):
        try:
            """Perform FedAvg on a dictionary of model weights."""
            num_clients = len(weights_dict)
            avg_weights = None

            for client_weights in weights_dict.values():
                if avg_weights is None:
                    avg_weights = [torch.tensor(w) for w in client_weights]
                else:
                    avg_weights = [
                        avg + torch.tensor(w)
                        for avg, w in zip(avg_weights, client_weights)
                    ]

            avg_weights = [avg / num_clients for avg in avg_weights]
            return [w.numpy() for w in avg_weights]
        except:
            print("Error in perform_fedavg")


def generate_client_fn(
    trainloaders, valloaders, num_classes, difficulty, use_blockchain
):
    """Return a function that can be used by the VirtualClientEngine.

    to spawn a FlowerClient with client id `cid`.
    """

    def client_fn(cid: str):
        # This function will be called internally by the VirtualClientEngine
        # Each time the cid-th client is told to participate in the FL
        # simulation (whether it is for doing fit() or evaluate())

        # Returns a normal FLowerClient that will use the cid-th train/val
        # dataloaders as it's local data.
        return FlowerClient(
            trainloader=trainloaders[int(cid)],
            vallodaer=valloaders[int(cid)],
            num_classes=num_classes,
            difficulty=difficulty,
            use_blockchain=use_blockchain,
        )

    # return the function to spawn client
    return client_fn
