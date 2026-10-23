/**
 * Une carte de crédit.
 * Hérite de {@link Wallet} et implémente {@link IPaymentProcessor}.
 */
public class CreditCard extends Wallet implements IPaymentProcessor {

    private String cardNumber;

    public CreditCard() {
        super();
    }

    public CreditCard(String cardNumber) {
        super();
        this.cardNumber = cardNumber;
    }

    public String getCardNumber() {
        return cardNumber;
    }

    public void setCardNumber(String cardNumber) {
        this.cardNumber = cardNumber;
    }

    /**
     * Traite un paiement avec cette carte de crédit.
     */
    @Override
    public void processPayment() {
        // TODO: implémenter la logique de traitement du paiement
    }

    /**
     * Débite la carte de crédit.
     */
    public void charge() {
        // TODO: implémenter la logique de débit de la carte
    }
}
