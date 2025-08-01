"""Kuadrant CR"""

import dataclasses

from openshift_client import selector

from testsuite.kuadrant.authorino import Authorino
from testsuite.kubernetes import CustomResource, modify
from testsuite.kubernetes.deployment import Deployment
from testsuite.utils import asdict


class KuadrantSection:
    """
    Base class for Kuadrant sub components:
        Authorino - spec.authorino
        Limitador - spec.limitador
    """

    def __init__(self, kuadrant_cr, spec_name):
        super().__init__()
        self.kuadrant_cr = kuadrant_cr
        self.spec_name = spec_name

    @property
    def deployment(self):
        """Returns Deployment object for CR"""
        with self.context:
            return selector("deployment", labels={"app": self.spec_name}).object(cls=Deployment)

    def name(self):
        """Overrides `name` method from `apiobject` so it returns name of Kuadrant section"""
        return self.spec_name

    def __getitem__(self, name):
        return self.kuadrant_cr.model.spec[self.spec_name][name]

    def __setitem__(self, name, value):
        if dataclasses.is_dataclass(value):
            self.kuadrant_cr.model.spec[self.spec_name][name] = asdict(value)
        else:
            self.kuadrant_cr.model.spec[self.spec_name][name] = value

    def __getattr__(self, item):
        try:
            return getattr(self.kuadrant_cr, item)
        except AttributeError as exc:
            raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{item}'") from exc


class AuthorinoSection(KuadrantSection, Authorino):
    """Authorino `spec.authorino` from KuadrantCR object"""

    def wait_for_ready(self):
        return super(KuadrantSection, self).wait_for_ready()

    @property
    def authorization_url(self):
        """Return service endpoint for authorization"""
        return f"{self.spec_name}-authorino-authorization.{self.namespace()}.svc.cluster.local"

    @property
    def oidc_url(self):
        """Return authorino oidc endpoint"""
        return f"{self.spec_name}-authorino-oidc.{self.namespace()}.svc.cluster.local"

    @property
    def metrics_service(self):
        """Returns Authorino metrics service APIObject"""
        with self.context:
            return selector(f"service/{self.spec_name}-controller-metrics").object()


class LimitadorSection(KuadrantSection):
    """Limitador `spec.limitador` from KuadrantCR object"""

    @property
    def deployment(self) -> Deployment:
        """Returns Deployment object for this Limitador"""
        with self.context:
            return selector(f"deployment/{self.name()}").object(cls=Deployment)

    @property
    def pod(self):
        """Returns Pod object for this Limitadaor"""
        with self.context:
            return selector("pod", labels={"app": self.name()}).object()


class KuadrantCR(CustomResource):
    """Represents Kuadrant CR objects"""

    @property
    def authorino(self) -> AuthorinoSection:
        """Returns spec.authorino from Kuadrant object"""
        self.model.spec.setdefault("authorino", {})
        return AuthorinoSection(self, "authorino")

    @property
    def limitador(self) -> LimitadorSection:
        """Returns spec.limitador from Kuadrant object"""
        self.model.spec.setdefault("limitador", {})
        return LimitadorSection(self, "limitador")

    @modify
    def set_observability(self, enabled: bool):
        """Enable observability"""
        self.model.spec["observability"] = {"enable": enabled} if enabled else None
