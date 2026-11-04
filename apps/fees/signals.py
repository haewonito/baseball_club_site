from django.db.models.signals import post_save
from django.dispatch import receiver

from .credits import apply_credit
from .models import Fee


@receiver(post_save, sender=Fee)
def apply_credit_to_new_or_changed_fee(sender, instance, raw=False, **kwargs):
    """A player's existing credit pays a newly created (or raised) fee automatically."""
    if not raw and instance.player_id:
        apply_credit(instance.player)
