import torch
import torch.nn as nn

from conditional_flow_matching.Model.Transformer.latent_array import LatentArrayTransformer


class MashLatentNet(torch.nn.Module):
    def __init__(
        self,
        n_latents=400,
        mask_degree: int = 3,
        sh_degree: int = 2,
        context_dim=768,
        n_heads=8,
        d_head=64,
        depth=24,
        sigma_min=0,
        sigma_max=float("inf"),
        sigma_data=1,
    ):
        super().__init__()

        self.n_latents = n_latents
        self.sigma_min = sigma_min
        self.sigma_max = sigma_max
        self.sigma_data = sigma_data

        self.mask_dim = 2 * mask_degree + 1
        self.sh_dim = (sh_degree + 1) ** 2

        self.channels = 9 + self.mask_dim + self.sh_dim

        self.category_emb = nn.Embedding(55, context_dim)

        self.model = LatentArrayTransformer(
            in_channels=self.channels,
            t_channels=256,
            n_heads=n_heads,
            d_head=d_head,
            depth=depth,
            context_dim=context_dim,
        )

        self.to_outputs = nn.Linear(self.channels, self.channels)
        return

    def emb_category(self, class_labels):
        return self.category_emb(class_labels).unsqueeze(1)

    def forwardCondition(self, mash_params, condition, t):
        delta_mash_feature = self.model(mash_params, t, cond=condition)
        delta_mash_params = self.to_outputs(delta_mash_feature)
        return delta_mash_params

    def forward(self, mash_params, condition, t, condition_drop_prob: float = 0.0):
        if condition.dtype == torch.float32:
            condition = condition + 0.0 * self.emb_category(torch.zeros([mash_params.shape[0]], dtype=torch.long, device=mash_params.device))
        else:
            condition = self.emb_category(condition)

        if len(t.shape) == 0:
            t = t.unsqueeze(0)

        # dropout context with some probability
        context_mask = torch.bernoulli(torch.ones_like(condition)-condition_drop_prob).to(mash_params.device)
        condition = condition * context_mask

        return self.forwardCondition(mash_params, condition, t)
