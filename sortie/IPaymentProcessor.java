/**
 * Interface pour les objets pouvant traiter un paiement.
 */
public interface IPaymentProcessor {

    /**
     * Traite un paiement.
     */
    void processPayment();
}
