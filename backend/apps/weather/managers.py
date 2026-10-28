"""Custom querysets/managers for weather models (docs/SERVICES/weather)."""

from django.db import models


class WeatherObservationQuerySet(models.QuerySet):
    def for_checkpoints(self, checkpoint_ids):
        """Stored observations for the given checkpoint ids."""
        return self.filter(checkpoint_id__in=checkpoint_ids)

    def at_forecast_time(self, forecast_time):
        """Observations valid at an explicit forecast time."""
        return self.filter(forecast_time=forecast_time)


class WeatherObservationManager(models.Manager.from_queryset(WeatherObservationQuerySet)):
    """Manager for :class:`~apps.weather.models.WeatherObservation`."""
