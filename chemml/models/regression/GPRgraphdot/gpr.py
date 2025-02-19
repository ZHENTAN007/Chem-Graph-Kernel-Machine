#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import pickle
import math
import numpy as np
from graphdot.model.gaussian_process.gpr import GaussianProcessRegressor
from graphdot.model.gaussian_process.nystrom import *


def _predict(predict, X, return_std=False, return_cov=False, memory_save=True,
             n_memory_save=10000):
    if return_cov or not memory_save:
        return predict(X, return_std=return_std, return_cov=return_cov)
    else:
        N = X.shape[0]
        y_mean = []
        y_std = []
        for i in range(math.ceil(N / n_memory_save)):
            X_ = X[i * n_memory_save:(i + 1) * n_memory_save]
            if return_std:
                [y_mean_, y_std_] = predict(
                    X_, return_std=return_std, return_cov=return_cov)
                y_std.append(y_std_)
            else:
                y_mean_ = predict(
                    X_, return_std=return_std, return_cov=return_cov)
            y_mean.append(y_mean_)
        if return_std:
            return np.concatenate(y_mean), np.concatenate(y_std)
        else:
            return np.concatenate(y_mean)


class GPR(GaussianProcessRegressor):
    def predict_(self, Z, return_std=False, return_cov=False):
        if not hasattr(self, 'Kinv'):
            raise RuntimeError('Model not trained.')
        Ks = self._gramian(Z, self.X)
        ymean = (Ks @ self.Ky) * self.y_std + self.y_mean
        if return_std is True:
            Kss = self._gramian(Z, diag=True)
            Kss.flat[::len(Kss) + 1] -= self.alpha
            std = np.sqrt(
                np.maximum(0, Kss - (Ks @ (self.Kinv @ Ks.T)).diagonal())
            )
            return (ymean, std)
        elif return_cov is True:
            Kss = self._gramian(Z)
            Kss.flat[::len(Kss) + 1] -= self.alpha
            cov = np.maximum(0, Kss - Ks @ (self.Kinv @ Ks.T))
            return (ymean, cov)
        else:
            return ymean

    def predict(self, X, return_std=False, return_cov=False):
        return _predict(self.predict_, X, return_std=return_std,
                        return_cov=return_cov)

    """
    def predict_loocv(self, Z, z, return_std=False):
        if z.ndim == 1:
            return super().predict_loocv(Z, z, return_std=return_std)
        else:
            if return_std:
                y_preds = []
                y_stds = []
                for i in range(z.shape[1]):
                    y_pred, y_std = super().predict_loocv(Z, z[:, i],
                                                          return_std=True)
                    y_preds.append(y_pred)
                    y_stds.append(y_std)
                return np.concatenate(y_preds).reshape(len(y_preds), len(Z)).T, \
                       np.concatenate(y_stds).reshape(len(y_stds), len(Z)).T
            else:
                y_preds = []
                for i in range(z.shape[1]):
                    y_pred = super().predict_loocv(Z, z[:, i],
                                                   return_std=False)
                    y_preds.append(y_pred)
                return np.concatenate(y_preds).reshape(len(y_preds), len(Z)).T
    """

    def predict_loocv(self, Z, z, return_std=False):
        assert(len(Z) == len(z))
        z = np.asarray(z)
        if self.normalize_y is True:
            z_mean, z_std = np.mean(z, axis=0), np.std(z, axis=0)
            z = (z - z_mean) / z_std
        else:
            z_mean, z_std = 0, 1
        Kinv, _ = self._invert(self._gramian(Z))
        Kinv_diag = (Kinv @ np.eye(len(Z))).diagonal()

        ymean = (z - ((Kinv @ z).T / Kinv_diag).T) * z_std + z_mean
        if return_std is True:
            std = np.sqrt(1 / np.maximum(Kinv_diag, 1e-14))
            return (ymean, std)
        else:
            return ymean

    @classmethod
    def load_cls(cls, f_model, kernel):
        store_dict = pickle.load(open(f_model, 'rb'))
        kernel = kernel.clone_with_theta(store_dict.pop('theta'))
        model = cls(kernel)
        model.__dict__.update(**store_dict)
        return model

    """sklearn GPR parameters"""

    @property
    def kernel_(self):
        return self.kernel

    @property
    def X_train_(self):
        return self._X

    @X_train_.setter
    def X_train_(self, value):
        self._X = value


class LRAGPR(GPR):
    r"""Accelerated Gaussian process regression (GPR) using the Nystrom low-rank
    approximation.

    Parameters
    ----------
    kernel: kernel instance
        The covariance function of the GP.
    alpha: float > 0, default = 1e-7
        Value added to the diagonal of the core matrix during fitting. Larger
        values correspond to increased noise level in the observations. A
        practical usage of this parameter is to prevent potential numerical
        stability issues during fitting, and ensures that the core matrix is
        always positive definite in the precense of duplicate entries and/or
        round-off error.
    beta: float > 0, default = 1e-7
        Threshold value for truncating the singular values when computing the
        pseudoinverse of the low-rank kernel matrix. Can be used to tune the
        numerical stability of the model.
    optimizer: one of (str, True, None, callable)
        A string or callable that represents one of the optimizers usable in
        the scipy.optimize.minimize method.
        If None, no hyperparameter optimization will be carried out in fitting.
        If True, the optimizer will default to L-BFGS-B.
    normalize_y: boolean
        Whether to normalize the target values y so that the mean and variance
        become 0 and 1, respectively. Recommended for cases where zero-mean,
        unit-variance kernels are used. The normalization will be
        reversed when the GP predictions are returned.
    kernel_options: dict, optional
        A dictionary of additional options to be passed along when applying the
        kernel to data.
    """

    def fit(self, *args, **kwargs):
        return self.fit(*args, **kwargs)

    @property
    def C(self):
        '''The core sample set for constructing the subspace for low-rank
        approximation.'''
        try:
            return self._C
        except AttributeError:
            raise AttributeError(
                'Core samples do not exist. Please provide using fit().'
            )

    @C.setter
    def C(self, C):
        self._C = C

    def _corespace(self, C=None, Kcc=None):
        assert (C is None or Kcc is None)
        if Kcc is None:
            Kcc = self._gramian(C)
        try:
            return powerh(Kcc, -0.5, return_symmetric=False)
        except np.linalg.LinAlgError:
            warnings.warn(
                'Core matrix singular, try to increase `alpha`.\n'
                'Now falling back to use a pseudoinverse.'
            )
            try:
                return powerh(Kcc, -0.5, rcond=self.beta, mode='clamp',
                              return_symmetric=False)
            except np.linalg.LinAlgError:
                raise np.linalg.LinAlgError(
                    'The core matrix is likely corrupted with NaNs and Infs '
                    'because a pseudoinverse could not be computed.'
                )

    def fit(self, C, X, y, loss='likelihood', tol=1e-5, repeat=1,
            theta_jitter=1.0, verbose=False):
        """Train a low-rank approximate GPR model. If the `optimizer` argument
        was set while initializing the GPR object, the hyperparameters of the
        kernel will be optimized using the specified loss function.

        Parameters
        ----------
        C: list of objects or feature vectors.
            The core set that defines the subspace of low-rank approximation.
        X: list of objects or feature vectors.
            Input values of the training data.
        y: 1D array
            Output/target values of the training data.
        loss: 'likelihood' or 'loocv'
            The loss function to be minimzed during training. Could be either
            'likelihood' (negative log-likelihood) or 'loocv' (mean-square
            leave-one-out cross validation error).
        tol: float
            Tolerance for termination.
        repeat: int
            Repeat the hyperparameter optimization by the specified number of
            times and return the best result.
        theta_jitter: float
            Standard deviation of the random noise added to the initial
            logscale hyperparameters across repeated optimization runs.
        verbose: bool
            Whether or not to print out the optimization progress and outcome.

        Returns
        -------
        self: LowRankApproximateGPR
            returns an instance of self.
        """
        self.C = C
        self.X = X
        self.y = y

        '''hyperparameter optimization'''
        if self.optimizer:

            if loss == 'likelihood':
                objective = self.log_marginal_likelihood
            elif loss == 'loocv':
                raise NotImplementedError(
                    '(ง๑ •̀_•́)ง LOOCV training not ready yet.'
                )

            opt = self._hyper_opt(
                lambda theta, objective=objective: objective(
                    theta, eval_gradient=True, clone_kernel=False,
                    verbose=verbose
                ),
                self.kernel.theta.copy(),
                tol, repeat, theta_jitter, verbose
            )
            if verbose:
                print(f'Optimization result:\n{opt}')

            if opt.success:
                self.kernel.theta = opt.x
            else:
                raise RuntimeError(
                    f'Training using the {loss} loss did not converge, got:\n'
                    f'{opt}'
                )

        '''build and store GPR model'''
        self.Kcc_rsqrt = self._corespace(C=self.C)
        self.Kxc = self._gramian(self.X, self.C)
        self.Fxc = self.Kxc @ self.Kcc_rsqrt
        self.Kinv = lr.dot(self.Fxc, rcond=self.beta, mode='clamp').inverse()
        self.Ky = self.Kinv @ self.y
        return self

    def predict_(self, Z, return_std=False, return_cov=False):
        """Predict using the trained GPR model.

        Parameters
        ----------
        Z: list of objects or feature vectors.
            Input values of the unknown data.
        return_std: boolean
            If True, the standard-deviations of the predictions at the query
            points are returned along with the mean.
        return_cov: boolean
            If True, the covariance of the predictions at the query points are
            returned along with the mean.

        Returns
        -------
        ymean: 1D array
            Mean of the predictive distribution at query points.
        std: 1D array
            Standard deviation of the predictive distribution at query points.
        cov: 2D matrix
            Covariance of the predictive distribution at query points.
        """
        if not hasattr(self, 'Kinv'):
            raise RuntimeError('Model not trained.')
        Kzc = self._gramian(Z, self.C)
        Fzc = Kzc @ self.Kcc_rsqrt
        Kzx = lr.dot(Fzc, self.Fxc.T)

        ymean = Kzx @ self.Ky * self.y_std + self.y_mean
        if return_std is True:
            Kzz = self._gramian(Z, diag=True)
            std = np.sqrt(
                np.maximum(Kzz - (Kzx @ self.Kinv @ Kzx.T).diagonal(), 0)
            )
            return (ymean, std * self.y_std)
        elif return_cov is True:
            Kzz = self._gramian(Z)
            cov = np.maximum(Kzz - (Kzx @ self.Kinv @ Kzx.T).todense(), 0)
            return (ymean, cov * self.y_std ** 2)
        else:
            return ymean

    def predict(self, X, return_std=False, return_cov=False):
        return _predict(self.predict_, X, return_std=return_std,
                        return_cov=return_cov)

    def predict_loocv(self, Z, z, return_std=False, method='auto'):
        """Compute the leave-one-out cross validation prediction of the given
        data.

        Parameters
        ----------
        Z: list of objects or feature vectors.
            Input values of the unknown data.
        z: 1D array
            Target values of the training data.
        return_std: boolean
            If True, the standard-deviations of the predictions at the query
            points are returned along with the mean.
        method: 'auto' or 'ridge-like' or 'gpr-like'
            Selects the algorithm used for fast evaluation of the leave-one-out
            cross validation without expliciting training one model per sample.
            'ridge-like' seems to be more stable with a smaller core size (that
            is not rank-deficit), while 'gpr-like' seems to be more stable with
            a larger core size. By default, the option is 'auto' and the
            function will choose a method based on an analysis on the
            eigenspectrum of the dataset.

        Returns
        -------
        ymean: 1D array
            Leave-one-out mean of the predictive distribution at query points.
        std: 1D array
            Leave-one-out standard deviation of the predictive distribution at
            query points.
        """
        assert (len(Z) == len(z))
        z = np.asarray(z)
        if self.normalize_y is True:
            z_mean, z_std = np.mean(z), np.std(z)
            z = (z - z_mean) / z_std
        else:
            z_mean, z_std = 0, 1

        if not hasattr(self, 'Kcc_rsqrt'):
            raise RuntimeError('Model not trained.')
        Kzc = self._gramian(Z, self.C)

        Cov = Kzc.T @ Kzc
        Cov.flat[::len(self.C) + 1] += self.alpha
        Cov_rsqrt, eigvals = powerh(
            Cov, -0.5, return_symmetric=False, return_eigvals=True
        )

        # if an eigenvalue is smaller than alpha, it would have been negative
        # in the unregularized Cov matrix
        if method == 'auto':
            if eigvals.min() > self.alpha:
                method = 'ridge-like'
            else:
                method = 'gpr-like'

        if method == 'ridge-like':
            P = Kzc @ Cov_rsqrt
            L = lr.dot(P, P.T)
            zstar = z - (z - L @ z) / (1 - L.diagonal())
            if return_std is True:
                raise NotImplementedError(
                    'LOOCV std using the ridge-like method is not ready yet.'
                )
        elif method == 'gpr-like':
            F = Kzc @ self.Kcc_rsqrt
            Kinv = lr.dot(F, rcond=self.beta, mode='clamp').inverse()
            zstar = z - (Kinv @ z) / Kinv.diagonal()
            if return_std is True:
                std = np.sqrt(1 / np.maximum(Kinv.diagonal(), 1e-14))
        else:
            raise RuntimeError(f'Unknown method {method} for predict_loocv.')

        if return_std is True:
            return (zstar * z_std + z_mean, std * z_std)
        else:
            return zstar * z_std + z_mean

    def log_marginal_likelihood(self, theta=None, C=None, X=None, y=None,
                                eval_gradient=False, clone_kernel=True,
                                verbose=False):
        """Returns the log-marginal likelihood of a given set of log-scale
        hyperparameters.

        Parameters
        ----------
        theta: array-like
            Kernel hyperparameters for which the log-marginal likelihood is
            to be evaluated. If None, the current hyperparameters will be used.
        C: list of objects or feature vectors.
            The core set that defines the subspace of low-rank approximation.
            If None, `self.C` will be used.
        X: list of objects or feature vectors.
            Input values of the training data. If None, `self.X` will be used.
        y: 1D array
            Output/target values of the training data. If None, `self.y` will
            be used.
        eval_gradient: boolean
            If True, the gradient of the log-marginal likelihood with respect
            to the kernel hyperparameters at position theta will be returned
            alongside.
        clone_kernel: boolean
            If True, the kernel is copied so that probing with theta does not
            alter the trained kernel. If False, the kernel hyperparameters will
            be modified in-place.
        verbose: boolean
            If True, the log-likelihood value and its components will be
            printed to the screen.

        Returns
        -------
        log_likelihood: float
            Log-marginal likelihood of theta for training data.
        log_likelihood_gradient: 1D array
            Gradient of the log-marginal likelihood with respect to the kernel
            hyperparameters at position theta. Only returned when eval_gradient
            is True.
        """
        theta = theta if theta is not None else self.kernel.theta
        C = C if C is not None else self.C
        X = X if X is not None else self.X
        y = y if y is not None else self.y

        if clone_kernel is True:
            kernel = self.kernel.clone_with_theta(theta)
        else:
            kernel = self.kernel
            kernel.theta = theta

        t_kernel = time.perf_counter()
        if eval_gradient is True:
            Kxc, d_Kxc = self._gramian(X, C, kernel=kernel, jac=True)
            Kcc, d_Kcc = self._gramian(C, kernel=kernel, jac=True)
        else:
            Kxc = self._gramian(X, C, kernel=kernel)
            Kcc = self._gramian(C, kernel=kernel)
        t_kernel = time.perf_counter() - t_kernel

        t_linalg = time.perf_counter()

        Kcc_rsqrt = self._corespace(Kcc=Kcc)
        F = Kxc @ Kcc_rsqrt
        K = lr.dot(F, rcond=self.beta, mode='clamp')
        K_inv = K.inverse()

        logdet = K.logdet()
        Ky = K_inv @ y
        yKy = y @ Ky
        logP = yKy + logdet

        if eval_gradient is True:
            D_theta = np.zeros_like(theta)
            K_inv2 = K_inv ** 2
            for i, t in enumerate(theta):
                d_F = d_Kxc[:, :, i] @ Kcc_rsqrt
                d_K = lr.dot(F, d_F.T) + lr.dot(d_F, F.T) - lr.dot(
                    F @ Kcc_rsqrt.T @ d_Kcc[:, :, i],
                    Kcc_rsqrt @ F.T
                )
                d_logdet = (K_inv @ d_K).trace()
                d_Kinv_part = K_inv2 @ d_K - K_inv2 @ d_K @ (K @ K_inv)
                d_Kinv = d_Kinv_part + d_Kinv_part.T - K_inv @ d_K @ K_inv
                d_yKy = d_Kinv.quadratic(y, y)
                D_theta[i] = (d_logdet + d_yKy) * np.exp(t)
            retval = (logP, D_theta)
        else:
            retval = logP

        t_linalg = time.perf_counter() - t_linalg

        if verbose:
            mprint.table(
                ('logP', '%12.5g', yKy + logdet),
                ('dlogP', '%12.5g', np.linalg.norm(D_theta)),
                ('y^T.K.y', '%12.5g', yKy),
                ('log|K| ', '%12.5g', logdet),
                ('Cond(K)', '%12.5g', K.cond()),
                ('GPU time', '%10.2g', t_kernel),
                ('CPU time', '%10.2g', t_linalg),
            )

        return retval
