#!/usr/bin/env python2.7
"""
Adam Stanford-Moore,Eric Nielsen, Bruce Macintosh, Rob De Rosa
Stanford University Physics Department
8/28/18
BAFFLES: Bayesian Ages for Field LowEr-mass Stars
"""

import ca_constants as const
from scipy import interpolate
from scipy.stats import norm,lognorm
from matplotlib.backends.backend_pdf import PdfPages
import matplotlib.pyplot as plt
import probability as prob
import fitting as my_fits
import numpy as np
import plotting as my_plot
import bisect
import sys
import copy
import utils
import time

# shortcut to quickly computing using default grids the posteriors for calcium and/or lithium
def baffles_age(bv=None,rhk=None,li=None,bv_err=None,li_err = None,upperLim=False,maxAge=const.GALAXY_AGE,fileName='baffles',pdfPage=None,showPlots=True,noPlots=False,savePostAsText=False):
    if (not rhk and not li):
        raise RuntimeError("Must provide at least one of calcium logR'HK or lithium EW")
    if (li and not bv):
        raise RuntimeError("Must provide B-V value with lithium EW")
    
    if (not pdfPage and not noPlots):
        pdfPage = PdfPages(fileName + '.pdf')
        
    p = None
    if (rhk):
        baf = age_estimator('calcium')
        p = baf.get_posterior(bv,rhk,pdfPage,showPlots,bv_err,li_err,upperLim=upperLim,maxAge=maxAge,mamajekAge=my_fits.getMamaAge(rhk))
        if (savePostAsText):
            np.savetxt(fileName + "_calcium.csv", zip(const.AGE,p.array), delimiter=",")
        print "Ca Median Age: %.3g Myr, 68%% CI: %.3g - %.3g Myr, 95%% CI: %.3g - %.3g Myr" % (p.stats[2],p.stats[1],p.stats[3],p.stats[0],p.stats[4])
    p2 = None
    if (li):
        baf2 = age_estimator('lithium')
        p2 = baf2.get_posterior(bv,li,pdfPage,showPlots,bv_err,li_err,upperLim=upperLim,maxAge=maxAge)
        if (savePostAsText):
            np.savetxt(fileName + "_lithium.csv", zip(const.AGE,p2.array), delimiter=",")
        
        if p2.upperLim: print "1 sig lower-lim: %.3g Myr, 2 sig lower-lim: %.3g Myr, 3 sig: %.3g Myr" % (p2.stats[2],p2.stats[1],p2.stats[0])
        else: print "Li Median Age: %.3g Myr, 68%% CI: %.3g - %.3g Myr, 95%% CI: %.3g - %.3g Myr" % (p2.stats[2],p2.stats[1],p2.stats[3],p2.stats[0],p2.stats[4])

    if (p and p2):
        title = ' Calcium/Lithium Posterior Product'
        y = p.array * p2.array
        prob.normalize(const.AGE,y)
        stats = prob.stats(const.AGE,y)
        my_plot.posterior(const.AGE,y,prob.stats(const.AGE,y),title,pdfPage,showPlots)
        print "Final Median Age: %.3g Myr, 68%% CI: %.3g - %.3g, 95%% CI: %.3g - %.3g" % (stats[2],stats[1],stats[3],stats[0],stats[4])

        if (savePostAsText):
            np.savetxt(fileName + "_product.csv", zip(const.AGE,y), delimiter=",")

    if pdfPage:
        pdfPage.close()

class posterior:
    def __init__(self):
        self.stats = None
        self.array = None
        self.upperLim = False


class age_estimator:
    #takes in a metal idicator either 'calcium' or 'lithium' denoting which method to use
    # option to input the grid_median and grid_sigma as arrays or as strings referencing saved .npy files
    def __init__(self,metal,grid_median=None,grid_sigma=None,default_grids=True):
        self.metal = metal
        self.grid_median = None
        self.grid_sigma = None
        self.const = self.init_constants(metal)
        if (grid_median and grid_sigma):
            self.set_grids(grid_median,grid_sigma)
        elif (default_grids):
            self.set_grids(self.const.DEFAULT_MEDIAN_GRID,self.const.DEFAULT_SIGMA_GRID)
    
    def set_grids(self,grid_median,grid_sigma):
        if (type(grid_median) == str and type(grid_median) == str):
            if (grid_median[-4:] != '.npy'):
                grid_median += '.npy'
            if (grid_sigma[-4:] != '.npy'):
                grid_sigma += '.npy'
            self.grid_median, self.grid_sigma = np.load(grid_median), np.load(grid_sigma)
        elif (type(grid_median) == 'numpy.ndarray'):
            self.grid_median, self.grid_sigma = grid_median, grid_sigma

    #Takes in bv the (B-V)o corrected color and the metallicity to return a posterior object.
    #Metallicity: log(R'HK) if refering to calcium. log equivalent width per mA if lithium.
    def get_posterior(self,bv,metallicity,pdfPage=None,showPlot=False,\
            bv_uncertainty=None,measure_err = None,upperLim=False,\
            maxAge=None,givenAge=None,givenErr = None,mamajekAge=None,title=None,\
            logPlot = False):
        if bv is None and self.metal=='calcium': bv = 0.65
        assert self.const.BV_RANGE[0] <= bv <= self.const.BV_RANGE[1], \
                "B-V of %.2f out of range. Valid range: " % bv + str(self.const.BV_RANGE)
        if self.metal=='calcium':
            assert self.const.METAL_RANGE[0] <= metallicity <= self.const.METAL_RANGE[1], \
                "Indicator value %.2f out of range. Valid range: " % metallicity + str(self.const.METAL_RANGE)
        elif self.metal=='lithium':
            assert self.const.METAL_RANGE_LIN[0] <= metallicity <= self.const.METAL_RANGE_LIN[1], \
                "Indicator value %.2f out of range. Valid range: " % metallicity + str(self.const.METAL_RANGE_LIN) + " mA"
        
        if mamajekAge == True and self.const.METAL_RANGE[0] <= metallicity <= \
                self.const.METAL_RANGE[1]:
            mamajekAge = my_fits.getMamaAge(metallicity)

        #if self.metal == 'lithium': metallicity = 10**metallicity 
        

        #print bv,metallicity,bv_uncertainty,measure_err

        posterior_arr = self.likelihood(bv,bv_uncertainty,metallicity,measure_err,\
                upperLim) * self.prior(maxAge)
        if all(posterior_arr == 0):
            print "Posterior not well defined. Area is zero so adding constant"
            posterior_arr += 1
        
        prob.normalize(self.const.AGE,posterior_arr)
        
        p_struct = posterior()
        p_struct.array = posterior_arr
        p_struct.stats = prob.stats(self.const.AGE,posterior_arr,upperLim)
        p_struct.upperLim = upperLim
        if (showPlot or pdfPage):
            if (title == None):
                title = 'Posterior Age Probabilty for (B-V)o = '+'%.2f' % bv \
                        +', ' + self.metal + ' = %.2f' % metallicity
            my_plot.posterior(self.const.AGE, p_struct.array, p_struct.stats,title,pdfPage,\
                    showPlot,givenAge=givenAge,givenErr=givenErr, mamajekAge=mamajekAge,logPlot=logPlot) 
        return p_struct
    
    def resample_posterior_product(self,bv_arr,metallicity_arr,bv_errs=None,measure_err_arr=None,\
            upperLim_arr=None,maxAge_arr = None, \
            pdfPage=None,showPlot=False,showStars=False,title=None,givenAge=None,givenErr = None,
            sample_num=None,numIter=4):
        if (bv_errs is None):
            bv_errs = [self.const.BV_UNCERTAINTY]*len(bv_arr)
        if upperLim_arr is None:
            upperLim_arr = [False]*len(metallicity_arr)
        if maxAge_arr is None:
            maxAge_arr = [None]*len(metallicity_arr)
        if measure_err_arr is None:
            measure_err_arr = [self.const.MEASURE_ERR]*len(metallicity_arr)
        if sample_num is None: sample_num = 15#len(bv_arr) - 5

        ln_prob = np.zeros(len(self.const.AGE))
        star_post = []
        
        resample_args = (bv_arr,metallicity_arr,bv_errs,measure_err_arr,upperLim_arr,maxAge_arr)
        args = (pdfPage,showPlot,showStars,title,givenAge,givenErr)

        post = prob.resample(self.posterior_product,resample_args,args,sample_num,numIter)

        prob.normalize(self.const.AGE,post)
        p_struct = posterior()
        p_struct.array = post
        p_struct.stats = prob.stats(self.const.AGE,post)

        if (showPlot or pdfPage):
            title = title if title else 'Resampled Posterior Product Age Distribution'
            my_plot.posterior(self.const.AGE, p_struct.array, p_struct.stats,title,\
                    pdfPage,showPlot,star_post,givenAge,givenErr=givenErr)
        return p_struct
    
    def posterior_product(self,bv_arr,metallicity_arr,bv_errs=None,measure_err_arr=None,\
            upperLim_arr=None,maxAge_arr = None, \
            pdfPage=None,showPlot=False,showStars=False,title=None,givenAge=None,givenErr = None):
        if (bv_errs is None):
            bv_errs = [self.const.BV_UNCERTAINTY]*len(bv_arr)
        if upperLim_arr is None:
            upperLim_arr = [False]*len(metallicity_arr)
        if maxAge_arr is None:
            maxAge_arr = [None]*len(metallicity_arr)
        if measure_err_arr is None:
            measure_err_arr = [self.const.MEASURE_ERR]*len(metallicity_arr)
        ln_prob = np.zeros(len(self.const.AGE))
        star_post = []
        
        np.seterr(divide = 'ignore')
        
        if self.metal == 'lithium' and np.mean(metallicity_arr) < 3: 
            metallicity_arr = np.power(10,metallicity_arr) 
        
        #max_list,min_list = [],[]

        sec_per_star = 0.5
        start=time.time()
        for i in range(len(bv_arr)):
            star_time=time.time()
            y = self.likelihood(bv_arr[i],bv_errs[i],metallicity_arr[i],measure_err_arr[i],\
                  upperLim_arr[i]) * self.prior(maxAge_arr[i])
            prob.normalize(self.const.AGE,y)
            inds = np.nonzero(y)[0]
            #max_list.append(self.const.AGE[inds[-1]])
            #min_list.append(self.const.AGE[inds[0]])
            #print "Age: %.3g / mamaAge: %.3g" % (prob.stats(self.const.AGE,y,upperLim_arr[i])[2], utils.getMamaAge(metallicity_arr[i]))
            #y = self.age_dist_uncertainty(bv_arr[i],bv_errs[i],metallicity_arr[i],upperLim_arr[i],\
            #    maxAge_arr[i])
            #if np.any(y <= 0):
            #    print "\n",bv_arr[i],metallicity_arr[i]
            #    print self.const.AGE[y <= 0][0]
            #    #plt.plot(self.const.AGE,y)
            #    #plt.show()
            ln_prob += np.log(y)
            if (showStars):
                #prob.normalize(self.const.AGE,y)
                star_post.append(y)
            utils.progress_bar(float(i+1)/len(bv_arr),int((len(bv_arr)-(i+1))*sec_per_star))
            sec_per_star = sec_per_star + 0.1*((time.time() - star_time) - sec_per_star) #exp moving average
            #sec_per_star = (time.time() - start)/float(i+1)

        print "Finished %d stars. Average time per star: %.2f seconds." % (len(bv_arr),(time.time() - start)/len(bv_arr))


        #print "Nonzero Range",max(min_list),min(max_list)
        post = np.exp(ln_prob - np.max(ln_prob))  #prevent underflow
        prob.normalize(self.const.AGE,post)
        p_struct = posterior()
        p_struct.array = post
        p_struct.stats = prob.stats(self.const.AGE,post)

        if (showPlot or pdfPage):
            my_plot.posterior(self.const.AGE, p_struct.array, p_struct.stats,title,\
                    pdfPage,showPlot,star_post,givenAge,givenErr=givenErr,bv_arr = bv_arr,metal=self.metal)

        #return p_struct.array
        return p_struct
    
    def init_constants(self,metal):
        if (metal[0].lower() == 'c'):
            self.metal = 'calcium'
            import ca_constants as const
        elif (metal[0].lower() == 'l'):
            self.metal = 'lithium'
            import li_constants as const
        else:
            raise RuntimeError("No metal specified. Please enter lithium or calcium")
        return const
   
    # Prior on age
    def prior(self,maxAge=None):
        agePrior = 1
        if maxAge is not None and maxAge < self.const.GALAXY_AGE:
            agePrior = self.const.AGE <= maxAge
        return agePrior
    
    def calcium_likelihood(self,bv,rhk):
        mu = self.grid_median 
        pdf_fit,cdf_fit = my_fits.fit_histogram(metal='calcium',fromFile=True)
        pdfs = pdf_fit((rhk - mu)/self.grid_sigma) / self.grid_sigma
        assert (pdfs >= 0).all(), "Error in numerical fit_histogram" + str(pdfs)
        return np.sum(pdfs,axis=0)

    # axes are (axis0=BV,axis1=AGE,axis2=Li)
    # assumes li is linear space
    def likelihood(self,bv,bv_uncertainty,li,measure_err,isUpperLim):
        if self.metal == 'calcium': return self.calcium_likelihood(bv,li)
        if not bv_uncertainty:
            bv_uncertainty = self.const.BV_UNCERTAINTY
        if not measure_err:
            measure_err = self.const.MEASURE_ERR
        

        pdf_fit,cdf_fit = my_fits.fit_histogram(metal=self.const.METAL_NAME,fromFile=True)
        #pdf_fit = lambda x: norm.pdf(x,loc=0,scale=0.17)
        #cdf_fit = lambda x: norm.cdf(x,loc=0,scale=0.17)
        
        BV = np.linspace(max(bv - 4*bv_uncertainty,self.const.BV_RANGE[0]),\
                min(bv + 4*bv_uncertainty,self.const.BV_RANGE[1]),300)
        bv_gauss = prob.gaussian(BV,bv,bv_uncertainty)
        BV,bv_gauss = prob.desample(BV,bv_gauss,self.const.NUM_BV_POINTS)
        
        #plt.plot(BV,bv_gauss)
        #plt.show()
        bv_gauss = bv_gauss.reshape(len(bv_gauss),1,1)

        f = interpolate.interp2d(self.const.AGE,self.const.BV_S,self.grid_median)
        mu = f(self.const.AGE,BV)

        if isUpperLim:
            #integration done in logspace with log li and log mu
            astro_gauss = cdf_fit(np.log10(li) - mu)
            final_sum = np.sum(astro_gauss,axis=0)
            #prob.normalize(self.const.AGE,final_sum)
            return final_sum

        mu = mu.reshape(mu.shape[0],mu.shape[1],1)  #CHANGED 10**

        li_gauss = prob.gaussian(self.const.METAL,li,measure_err)
        mask = li_gauss > prob.FIVE_SIGMAS
        li_gauss = li_gauss[mask]
        li_gauss = li_gauss.reshape(1,1,len(li_gauss))
        METAL = self.const.METAL[mask]
        METAL = METAL.reshape(1,1,len(METAL))
        
        astro_gauss = pdf_fit(np.log10(METAL) - mu)/METAL
        product = li_gauss*astro_gauss
        integral = np.trapz(product,METAL,axis=2)
        final_sum = np.sum(integral,axis=0)
        return final_sum

    #calculates and returns a 2D array of sigma b-v and age
    #omit_cluster specifies a cluster index to remove from the fits to make the grids without a cluster
    def make_grids(self,bv_li,fits,upper_lim=None,medianSavefile=None,sigmaSavefile=None,\
            setAsDefaults=False, omit_cluster=None):
        if (medianSavefile and medianSavefile[-4:] == '.npy'):
            medianSavefile = medianSavefile[:-4]
        if (sigmaSavefile and sigmaSavefile[-4:] == '.npy'):
            sigmaSavefile = sigmaSavefile[:-4]

        primordial_li_fit = None
        bldb_fit = None
        li_scatter_fit = None #fit as function of LiEW
        if (self.metal == 'lithium'):
            primordial_li_fit = my_fits.MIST_primordial_li()#ngc2264_fit),fromFile=False,saveToFile=True)
            bldb_fit = my_fits.bldb_fit(fits)
            li_scatter_fit = my_fits.fit_two_scatters(bv_li,fits,upper_lim=upper_lim,\
                    omit_cluster=omit_cluster)
        
        median_rhk, sigma = [],[] #holds the grids
        for bv in self.const.BV_S:
            rhk,scatter,CLUSTER_AGES,_ = my_fits.get_valid_metal(bv,fits,self.const,\
                    primordial_li_fit,bldb_fit,omit_cluster)
            mu,sig,_ = my_fits.vs_age_fits(bv,CLUSTER_AGES,rhk,scatter,self.metal,li_scatter_fit,omit_cluster)
            median_rhk.append(mu(self.const.AGE))
            sigma.append(sig(self.const.AGE))
            
        median_rhk,sigma = np.array(median_rhk),np.array(sigma)

        if (medianSavefile and sigmaSavefile):
            np.save(medianSavefile, median_rhk)
            np.save(sigmaSavefile, sigma)

        if (setAsDefaults):
            self.set_default_grids(medianSavefile,sigmaSavefile)
    
        self.grid_median, self.grid_sigma = median_rhk, sigma

    #given an x_value, which is the location to evaluate and an array of fits,
    #it calculates the y-value at x_val for each fit and returns an array of them
    def arrayFromFits(self,x_val,fits):
        arr = []
        for fit in fits:
            arr.append(fit(x_val))
        return arr

    def get_grids(self):
        return self.grid_median, self.grid_sigma

    #changes constant file to have these names as default grid names
    def set_default_grids(self,grid_median,grid_sigma):
        filename = 'ca_constants.py'
        if (self.metal=='lithium'):
            filename = 'li_constants.py'
        lines = open(filename,'r').readlines()
        for l in range(len(lines)):
            if (lines[l][:14] == 'DEFAULT_MEDIAN'):
                lines[l] = 'DEFAULT_MEDIAN_GRID = "' + grid_median + '.npy"\n'
            if (lines[l][:13] == 'DEFAULT_SIGMA'):
                lines[l] = 'DEFAULT_SIGMA_GRID = "' + grid_sigma + '.npy"\n'
        out = open(filename,'w')
        out.writelines(lines)
        out.close()


if  __name__ == "__main__":
    const = utils.init_constants('lithium')
    err = "Usage:  python2.7 baffles.py -bmv <B-V> -rhk <Log10(R\'HK)> -li <EWLi> [-bmv_err <> -li_err <> -ul -maxAge <13000> -noPlot -s -showPlot -filename <> -help]"
    
    help_msg = "\n\
    -bmv corrected (B-V)o of the star (optional for calcium)\n\
    -rhk <> log base 10 of the R'HK value \n\
    -li <> EW measure in milli-angstroms (=0.1 pm) \n\
    \noptional flags:\n\
    -ul indicates that the log(EW/mA) reading is an upper-limit reading. \n\
    -maxAge allows user to input max posible age of star (Myr) if upper-limit flag is used. default is %d \n\
    -bmv_err <float uncertainity> provides the uncertainty on B-V with default %f \n\
    -li_err <float uncertainity> provides the uncertainty in LiEW measurement with default %dmA \n\
    -noPlot suppresses all plotting and just generates .csv files (-s extension is implied. Used with -showplots it prevents saving).\n\
    -s saves posteriors as .csv \n\
    -showPlot to show posterior plots to user before saving. \n\
    -filename <name of file w/o extension> name of files to be saved: name.pdf is graphs, name_calcium.csv/name_lithium.csv/name_product.csv are posterior csv files for calcium/lithium/product respectively.  csv is stored as age, probability in two 1000 element columns.\n\
    -help prints this message \n" % (const.GALAXY_AGE,const.BV_UNCERTAINTY, const.MEASURE_ERR)
    
    argv = sys.argv #starts with 'baffles.py'
    if (len(argv) < 3 or '-help' in argv):
        print err,help_msg
        sys.exit()
    bv = None
    bv_err,li_err = None,None
    rhk, li = None,None
    save = False
    showPlots = False
    fileName = 'baffles'
    noPlots = False
    upperLim = False
    maxAge = const.GALAXY_AGE
    valid_flags = ['-bmv','-rhk','-li','-li_err','-bmv_err','-showPlot','-noPlot','-ul','-maxAge','-help']
    extra_flags = ['-showplot','-showPlots','-showplots','noPlots','-noplots','-noplot','-UL']
    for ar in argv[1:]:
        if not utils.isFloat(ar) and ar not in valid_flags and ar not in extra_flags:
            print "Invalid flag '" + ar + "'. Did you mean one of these:"
            print valid_flags
            exit()
    try:
        if ('-bmv' in argv):
            bv = float(argv[argv.index('-bmv') + 1])
        if ('-rhk' in argv):
            rhk = float(argv[argv.index('-rhk') + 1])
            import ca_constants as const
            if bv is not None and (not (const.BV_RANGE[0] <= bv <= const.BV_RANGE[1])):
                print "B-V out of range. Must be in range " + str(const.BV_RANGE)
                sys.exit()
            if (not (const.METAL_RANGE[0] <= rhk <= const.METAL_RANGE[1])):
                print "Log(R\'HK) out of range. Must be in range " + str(const.METAL_RANGE)
                sys.exit()
        if ('-li' in argv):
            li = float(argv[argv.index('-li') + 1])
            import li_constants as const
            if 0 < li < 3:
                print "Interpretting LiEW as log(LiEW)"
                li = 10**li
            
            if (not (const.BV_RANGE[0] <= bv <= const.BV_RANGE[1])):
                print "B-V out of range. Must be in range " + str(const.BV_RANGE)
                sys.exit()
            if (not (const.METAL_RANGE_LIN[0] <= li <= const.METAL_RANGE_LIN[1])):
                print "Li EW out of range. Must be in range " + str(const.METAL_RANGE) + " mA"
                sys.exit()
        if ('-s' in argv):
            save = True
        if ('-showplots' in argv or '-showplot' in argv or '-showPlots' in argv or '-showPlot' in argv):
            showPlots = True
        if ('-noplot' in argv or '-noplots' in argv or '-noPlots' in argv or '-noPlot' in argv):
            noPlots = True
            save = True
        if ('-filename' in argv):
            fileName = argv[argv.index('-filename') + 1]
        if ('-bmv_err' in argv):
            bv_err = float(argv[argv.index('-bmv_err') + 1])
        if ('-li_err' in argv):
            li_err = float(argv[argv.index('-li_err') + 1])
        if ('-ul' in argv or '-UL' in argv):
            upperLim = True
        if ('-maxAge' in argv):
            maxAge = float(argv[argv.index('-maxAge') + 1])
    except IndexError:
        print err
    except ValueError:
        print err
    
    baffles_age(bv,rhk,li,bv_err,li_err,upperLim,maxAge,fileName,showPlots=showPlots,noPlots=noPlots, savePostAsText=save)
