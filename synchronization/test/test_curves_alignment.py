import numpy as np
from scipy.interpolate import interp1d
import matplotlib.pyplot as plt
from scipy.optimize import minimize


# ----------------------     definition des courbes test  f_A et f_B   ------------------------------------------------
def courbes_fA_fB():
    x_A = [0,2,4,6,8,10,12,16,18, 21,22,24,26,28,30,32,34,36,38,40,42,44,46,48,50,52,54,56,62,64,70]
    y_A = [0,0,0,0,2, 3, 4, 6, 7,8.5, 9, 8, 7, 6, 5, 4, 5, 6, 7, 8, 9, 8, 7, 5, 4, 3, 3, 3, 3, 3, 3]
    y_A = [y_A[i]*360/9 for i in range(len(x_A))]
    rng = np.random.default_rng(6789)
    alea = rng.integers(low=-30, high=30, size=len(y_A))
    y_A = [y_A[i] + 0.18 * alea[i]  for i in range(len(y_A))]
    start_Point_A = 6
    start_Point_B = 120
    x_B = [100,103,106,109,111,114,117,120,123,126,129,131,134,137,140,143,146,149,152,155,158,161,164,167,170,173,176,
           179,182,185,188,191,194,197,200]
    x_B = [x_B[i] + shift for i in range(len(x_B))]
    y_B = [  0,  0,  0,  0,  0,  0,  0,  0,2.4,3.2,5.0,6.5,8.1,8.5,6.5,5.0,4.0,5.5,7.0,8.7,8.1,6.7,4.1,  3,  3,  3,  3,
             3,  3,  3,  3,  3,  3,  3,  3]
    y_B = [y_B[i] * 360 / 9 for i in range(len(x_B))]
    rng = np.random.default_rng(12345)
    alea = rng.integers(low=-30, high =30, size= len(y_B))
    y_B = [y_B[i] + 0.15* alea[i]  for i in range(len(y_B))]  # angle modifié à +/- 3°
    return x_A, y_A, x_B, y_B
# ---------------------------------------------------------------------------------------------------------------------


def domaine_interpol (x):
    x_interpol = np.linspace(min(x), max(x), num=300, endpoint=True)
    return x_interpol


def interpol_func(x, y, option='linear'):
    f = interp1d(x, y, kind=option)
    return  f


def cost_function(shift_x):
    # récupération des deux courbes à supperposer
    x_A, y_A ,x_B, y_B = courbes_fA_fB()
    # construct interpolator of f_A and f_B
    f_A = interpol_func(x_A, y_A, option='linear')
    f_B = interpol_func(x_B, y_B, option='linear')
    cost_function = 0.
    for i in range(len(x_A)):
        if x_B[0] <= x_A[i] + shift_x <= x_B[-1]:
            cost_function = cost_function + (f_A(x_A[i]) - f_B(x_A[i] + shift_x)) ** 2
        elif x_B[0] > x_A[i] + shift_x:
            cost_function = cost_function + (f_A(x_A[i]) ** 2)  # assume f_B equal zero before x_B[O]
        else:   # x_B[-1] < x_A[i] + shift_x
            cost_function = cost_function + (f_A(x_A[i]) ** 2)
    cost_function = np.sqrt(cost_function/np.average(x_A)**2)/len(x_A)
    return cost_function


# -- Variables globales
#  Pour les tests. Variable  "Shift"  testée de -300s à 3600s. Ce shift s'ajoute au décalage de base qui est de 114s
shift = -36.
# type d'interpolateur. linear (best!)  | zero, slinear, quadratic, cubic (spline d'ordre 0, 1, 2 et 3)
# spline d'odre zero (bad!!), slinear (idem linear), spline d'orde 2 ou 3 (création d'oscillations ... pas de sens phy)

if __name__ == "__main__":
    x_A, y_A ,x_B, y_B = courbes_fA_fB()
    # --calcul du shift initial (basé sur la distance des pics des deux courbes)
    n_A = np.argmax(y_A)
    n_B = np.argmax(y_B)
    shift_0 = x_B[n_B] - x_A[n_A]
    # ------- optimisation
    res = minimize(cost_function, shift_0, method='Nelder-Mead', options={'xatol': 10**-8, 'disp': True})


    print('Optimum initial   Time shift  = %.5f s.  Coût %.5f \n'
          'Optimum final     Time shift  = %.5f s.  Coût %.5f '
          % (shift_0, cost_function(shift_0),res.x, cost_function(res.x)))

    # -------   Visualisation des résultats
    # construction des interpolateurs
    x_fit = [x_B[i] - res.x for i in range(1, len(x_B))]
    f_A = interpol_func(x_A, y_A, option='linear')
    f_B = interpol_func(x_B, y_B, option='linear')
    plt.plot(x_A, y_A, 'o:',  x_B, y_B, 'o:', x_fit, f_B ([x_B[i] for i in range(1, len(x_B))]), '-')
    x_B_interp = domaine_interpol(x_B[1:])
    plt.plot(x_B_interp, f_B(x_B_interp), '--')
    plt.legend(['data_A',   'data_B', ' B fit'], loc='best')
    plt.grid()
    plt.title(' Time shift  = %.5f  s' % (res.x))
    plt.show()

